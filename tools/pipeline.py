#!/usr/bin/env python3
"""Otter Shell Nix pipeline — generate, lock, check, pin, audit, update.

Usage:
  ./tools/pipeline.py generate [--source-root DIR] [--check]
  ./tools/pipeline.py lock [--source-root DIR] [--output-dir DIR] [--zig PATH] [--check]
  ./tools/pipeline.py check [framework|compat|manifest|all] [--source-root DIR]
  ./tools/pipeline.py pin release VERSION
  ./tools/pipeline.py pin heads
  ./tools/pipeline.py audit
  ./tools/pipeline.py update [PIN ...]
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
PIKA_PREFIX = "git+https://git.pika-os.com/otter-shell/"
HEX_REV = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
SRI_SHA256 = re.compile(r"^sha256-[A-Za-z0-9+/]{43}=$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True, cwd=cwd
    )


def nix_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def quoted(text: str) -> str:
    return json.dumps(text)


def matching_brace(text: str, opening: int) -> int:
    depth = 0
    quote = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            continue
        if char == '"':
            quote = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"unclosed ZON struct starting at byte {opening}")


def strip_comments(text: str) -> str:
    """Remove Zig line/block comments while preserving strings."""
    out: list[str] = []
    i = 0
    quote = False
    escaped = False
    line_comment = False
    block_depth = 0
    while i < len(text):
        char = text[i]
        pair = text[i: i + 2]
        if line_comment:
            if char == "\n":
                line_comment = False
                out.append(char)
            else:
                out.append(" ")
            i += 1
            continue
        if block_depth:
            if pair == "/*":
                block_depth += 1
                out.extend("  ")
                i += 2
            elif pair == "*/":
                block_depth -= 1
                out.extend("  ")
                i += 2
            else:
                out.append("\n" if char == "\n" else " ")
                i += 1
            continue
        if quote:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            i += 1
            continue
        if pair == "//":
            line_comment = True
            out.extend("  ")
            i += 2
        elif pair == "/*":
            block_depth = 1
            out.extend("  ")
            i += 2
        else:
            out.append(char)
            if char == '"':
                quote = True
            i += 1
    return "".join(out)


def string_field(struct: str, name: str) -> str | None:
    match = re.search(rf'\.{re.escape(name)}\s*=\s*"((?:\\.|[^\"])*)"', struct)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except json.JSONDecodeError as _:
        return None  # not a valid JSON string escape sequence


def first(pattern: str, text: str, path: Path) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"could not parse {pattern!r} from {path}")
    return match.group(1)


def npins_get_path(pin: str) -> Path:
    """Resolve npins pin to a store path, with nix builtin fallback."""
    try:
        output = str(subprocess.check_output(["npins", "get-path", pin], cwd=ROOT, text=True, timeout=120).strip())
        if output:
            path = Path(output)
            if path.is_dir():
                return path
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    pins_file = ROOT / "npins/sources.json"
    if not pins_file.is_file():
        raise SystemExit(f"npins/sources.json is missing, cannot resolve {pin}")
    try:
        pins = json.loads(pins_file.read_text()).get("pins", {})
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid npins/sources.json: {e}") from e
    pin_data = pins.get(pin)
    if not pin_data:
        raise SystemExit(f"no npins pin for {pin}")
    repo_data = pin_data.get("repository", {})
    revision = pin_data.get("revision")
    submodules = pin_data.get("submodules", False)
    if submodules and isinstance(repo_data, dict):
        git_url = f"https://github.com/{repo_data['owner']}/{repo_data['repo']}.git"
        expr = f'(toString (builtins.fetchGit {{ url = "{git_url}"; rev = "{revision}"; submodules = true; }}))'
    else:
        url = pin_data.get("url")
        if not url and isinstance(repo_data, dict) and revision:
            url = f"https://github.com/{repo_data['owner']}/{repo_data['repo']}/archive/{revision}.tar.gz"
        if not url:
            raise SystemExit(f"cannot construct URL for npins pin {pin}")
        expr = f'(toString (builtins.fetchTarball {{ url = "{url}"; }}))'
    try:
        raw = subprocess.check_output(
            ["nix", "eval", "--impure", "--raw", "--expr", expr],
            cwd=ROOT, text=True, timeout=120,
        )
        output = str(raw.strip())
        path = Path(output)
        if path.is_dir():
            return path
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        raise SystemExit(f"could not resolve npins source {pin}: {e}") from e
    raise SystemExit(f"resolved path is not a directory for {pin}")


# ---------------------------------------------------------------------------
# Subcommand: generate — repositories.nix + SOURCE-ANALYSIS.json
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Repository:
    pin: str
    snapshotVersion: str
    minimumZigVersion: str
    directDeps: list[str]
    hasRemoteDeps: bool
    systemLibraries: list[str]


def _find_sources(source_root: Path | None) -> dict[str, Path]:
    if source_root is not None:
        return {
            path.name: path
            for path in sorted(source_root.glob("otter-*"))
            if path.is_dir() and (path / "build.zig.zon").is_file()
        }
    pins_file = ROOT / "npins/sources.json"
    if not pins_file.is_file():
        raise SystemExit("npins/sources.json is missing; pass --source-root or run `pin release`")
    try:
        pins = json.loads(pins_file.read_text()).get("pins", {})
    except json.JSONDecodeError as e:
        raise SystemExit(f"invalid npins/sources.json: {e}") from e
    result: dict[str, Path] = {}
    for pin_name in sorted(pins):
        if not pin_name.startswith("otter_"):
            continue
        try:
            source = npins_get_path(pin_name)
        except SystemExit:
            continue
        if (source / "build.zig.zon").is_file():
            result[pin_name.replace("_", "-")] = source
    return result


def _zon_urls(text: str) -> list[str]:
    return re.findall(r'\.url\s*=\s*"([^"]+)"', strip_comments(text))


def _otter_repo_from_url(url: str) -> str | None:
    match = re.match(
        r"^(?:git\+)?https://git\.pika-os\.com/otter-shell/"
        r"(otter-[A-Za-z0-9_-]+?)(?:\.git)?(?:[?#].*)?$",
        url,
    )
    return match.group(1) if match else None


def _reachable_manifests(root_path: Path) -> list[Path]:
    root_path = root_path.resolve()
    pending = [(root_path / "build.zig.zon").resolve()]
    seen: set[Path] = set()
    while pending:
        manifest = pending.pop()
        if manifest in seen or not manifest.is_file():
            continue
        seen.add(manifest)
        for relative in re.findall(r'\.path\s*=\s*"([^"]+)"', strip_comments(manifest.read_text())):
            child = (manifest.parent / relative).resolve()
            try:
                child.relative_to(root_path)
            except ValueError:
                continue
            pending.append(child / "build.zig.zon")
    return sorted(seen)


def _inspect_repo(name: str, path: Path) -> Repository:
    zon_path = path / "build.zig.zon"
    zon_text = zon_path.read_text()
    build_text = (path / "build.zig").read_text() if (path / "build.zig").is_file() else ""

    path_deps = re.findall(r'\.path\s*=\s*"\.\./(otter-[^/"]+)(?:/[^"]*)?"', zon_text)
    url_deps = [d for url in _zon_urls(zon_text) if (d := _otter_repo_from_url(url)) is not None]
    deps = sorted(set(path_deps + url_deps))
    remote_has_deps = any(
        _otter_repo_from_url(url) is None
        for nested in _reachable_manifests(path)
        for url in _zon_urls(nested.read_text())
    )
    libraries = sorted(set(re.findall(r'linkSystemLibrary\s*\(\s*"([^"]+)"', build_text)))
    return Repository(
        pin=name.replace("-", "_"),
        snapshotVersion=first(r'\.version\s*=\s*"([^"]+)"', zon_text, zon_path),
        minimumZigVersion=first(r'\.minimum_zig_version\s*=\s*"([^"]+)"', zon_text, zon_path),
        directDeps=deps,
        hasRemoteDeps=remote_has_deps,
        systemLibraries=libraries,
    )


def _render_nix(repositories: dict[str, Repository]) -> str:
    lines = ["# Generated by tools/pipeline.py generate.", "{"]
    for name, repo in sorted(repositories.items()):
        deps = " ".join(quoted(d) for d in repo.directDeps)
        libs = " ".join(quoted(l) for l in repo.systemLibraries)
        lines += [
            f"  {quoted(name)} = {{",
            f"    pin = {quoted(repo.pin)};",
            f"    snapshotVersion = {quoted(repo.snapshotVersion)};",
            f"    minimumZigVersion = {quoted(repo.minimumZigVersion)};",
            f"    directDeps = [ {deps} ];",
            f"    hasRemoteDeps = {'true' if repo.hasRemoteDeps else 'false'};",
            f"    systemLibraries = [ {libs} ];",
            "  };",
        ]
    lines.append("}")
    return "\n".join(lines) + "\n"


def cmd_generate(args: argparse.Namespace) -> int:
    paths = _find_sources(args.source_root)
    repositories = {name: _inspect_repo(name, path) for name, path in paths.items()}
    unknown = sorted({dep for r in repositories.values() for dep in r.directDeps} - repositories.keys())
    if unknown:
        raise SystemExit("missing sibling repositories: " + ", ".join(unknown))

    nix = _render_nix(repositories)
    nix_path = ROOT / "nix/repositories.nix"
    if args.check:
        if not nix_path.is_file() or nix_path.read_text() != nix:
            raise SystemExit("nix/repositories.nix is stale; regenerate it")
    else:
        nix_path.write_text(nix)

    specs_text = (ROOT / "nix/package-specs.nix").read_text()
    packages = sorted(set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', specs_text, re.MULTILINE)))
    analysis = {
        "snapshot": Counter(r.snapshotVersion for r in repositories.values()).most_common(1)[0][0],
        "repositories": {name: asdict(r) for name, r in sorted(repositories.items())},
        "packages": packages,
    }
    fp = ROOT / "SOURCE-ANALYSIS.json"
    rendered = json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not fp.is_file() or fp.read_text() != rendered:
            raise SystemExit("SOURCE-ANALYSIS.json is stale; regenerate it")
    else:
        fp.write_text(rendered)

    print(f"inspected {len(repositories)} Zig repositories and {len(packages)} package specs")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: lock — Zig dependency locks
# ---------------------------------------------------------------------------

PARSED_REPOS_CACHE: list[tuple[str, str]] | None = None


def _parse_repositories() -> list[tuple[str, str]]:
    global PARSED_REPOS_CACHE
    if PARSED_REPOS_CACHE is not None:
        return PARSED_REPOS_CACHE
    text = (ROOT / "nix/repositories.nix").read_text()
    result: list[tuple[str, str]] = []
    for block in re.finditer(r'^\s*"(otter-[^"]+)"\s*=\s*\{(.*?)^\s*\};', text, re.MULTILINE | re.DOTALL):
        body = block.group(2)
        if "hasRemoteDeps = true;" not in body:
            continue
        pin = re.search(r'\bpin\s*=\s*"([^"]+)";', body)
        if not pin:
            raise ValueError(f"{block.group(1)} has no npins pin")
        result.append((block.group(1), pin.group(1)))
    PARSED_REPOS_CACHE = result
    return result


def _dependency_structs(zon_file: Path) -> list[str]:
    text = strip_comments(zon_file.read_text())
    match = re.search(r"\.dependencies\s*=\s*\.\s*\{", text)
    if not match:
        return []
    opening = text.find("{", match.start())
    closing = matching_brace(text, opening)
    body = text[opening + 1: closing]
    structs: list[str] = []
    cursor = 0
    field = re.compile(r"\.(?:[A-Za-z_][A-Za-z0-9_]*|@\"(?:\\.|[^\"])+\")\s*=\s*\.\s*\{")
    while cursor < len(body):
        m = field.search(body, cursor)
        if not m:
            break
        prefix = body[: m.start()]
        if prefix.count("{") != prefix.count("}"):
            cursor = m.end()
            continue
        opening_brace = body.find("{", m.start())
        closing_brace = matching_brace(body, opening_brace)
        structs.append(body[opening_brace + 1: closing_brace])
        cursor = closing_brace + 1
    return structs


@dataclass(frozen=True)
class DependencySpec:
    zig_hash: str
    url: str


def _scan_manifest(zon_file: Path, boundary: Path) -> list[DependencySpec]:
    boundary = boundary.resolve()
    pending = [zon_file.resolve()]
    seen: set[Path] = set()
    result: list[DependencySpec] = []
    while pending:
        manifest = pending.pop()
        if manifest in seen or not manifest.is_file():
            continue
        seen.add(manifest)
        for struct in _dependency_structs(manifest):
            url = string_field(struct, "url")
            zig_hash = string_field(struct, "hash")
            path = string_field(struct, "path")
            if url:
                if not zig_hash:
                    raise ValueError(f"{manifest}: URL dependency has no .hash")
                if not url.startswith(PIKA_PREFIX):
                    result.append(DependencySpec(zig_hash=zig_hash, url=url))
                continue
            if not path:
                continue
            child = (manifest.parent / path).resolve()
            try:
                child.relative_to(boundary)
            except ValueError:
                continue
            pending.append(child / "build.zig.zon")
    return result


def _url_quality(url: str) -> tuple[int, str]:
    if not url.startswith("git+"):
        return (0, url)
    fragment = unquote(url.rsplit("#", 1)[-1]) if "#" in url else ""
    if HEX_REV.fullmatch(fragment):
        return (0, url)
    if fragment not in {"main", "master", "HEAD"}:
        return (1, url)
    return (2, url)


def _add_spec(specs: dict[str, DependencySpec], spec: DependencySpec) -> None:
    prev = specs.get(spec.zig_hash)
    if prev is None or _url_quality(spec.url) < _url_quality(prev.url):
        specs[spec.zig_hash] = spec


def _flake_prefetch(ref: str) -> dict[str, str]:
    cmd = ["nix", "flake", "prefetch", "--json",
           "--extra-experimental-features", "nix-command flakes", ref]
    try:
        return json.loads(run(cmd).stdout)
    except (json.JSONDecodeError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"flake prefetch failed for {ref}: {e}") from e


def _archive_prefetch(url: str) -> dict[str, str]:
    cmd = ["nix", "store", "prefetch-file", "--json",
           "--extra-experimental-features", "nix-command", url]
    try:
        return json.loads(run(cmd).stdout)
    except (json.JSONDecodeError, subprocess.CalledProcessError) as e:
        raise RuntimeError(f"archive prefetch failed for {url}: {e}") from e


def _resolve_git_revision(url: str, fragment: str) -> str:
    candidates = (
        (f"refs/tags/{fragment}^{{}}", f"refs/tags/{fragment}"),
        (f"refs/heads/{fragment}",),
        (fragment,),
    )
    failures: list[str] = []
    for refs in candidates:
        try:
            result = run(["git", "ls-remote", url, *refs], cwd=ROOT)
        except subprocess.CalledProcessError as e:
            failures.append(e.stderr.strip())
            continue
        matches = {rf: rev for rev, rf in (l.split("\t", 1) for l in result.stdout.splitlines() if "\t" in l)}
        for ref in refs:
            if ref in matches:
                return matches[ref]
    detail = "\n".join(f for f in failures if f)
    raise RuntimeError(f"could not resolve git ref {fragment!r} from {url}" + (f":\n{detail}" if detail else ""))


@dataclass
class FixedSource:
    kind: str
    url: str
    nix_hash: str
    store_path: Path
    rev: str | None = None


def _prefetch(spec: DependencySpec) -> FixedSource:
    if not spec.url.startswith("git+"):
        result = _archive_prefetch(spec.url)
        return FixedSource(kind="archive", url=spec.url, nix_hash=result["hash"], store_path=Path(result["storePath"]))
    raw = spec.url[4:]
    if "#" not in raw:
        raise ValueError(f"git dependency lacks a revision fragment: {spec.url}")
    base, fragment = raw.rsplit("#", 1)
    base = base.split("?", 1)[0]
    fragment = unquote(fragment)
    revision = fragment if HEX_REV.fullmatch(fragment) else _resolve_git_revision(base, fragment)
    result = _flake_prefetch(f"git+{base}?rev={revision}")
    return FixedSource(
        kind="git", url=base, rev=revision,
        nix_hash=result["hash"],
        store_path=Path(result["storePath"]),
    )


def _validate_and_scan(zig: str, fixed: FixedSource, expected: str) -> list[DependencySpec]:
    with tempfile.TemporaryDirectory(prefix="otter-zig-lock-") as td:
        tmp = Path(td)
        if fixed.kind == "archive":
            artifact = fixed.store_path
        else:
            artifact = tmp / "source.tar"
            with tarfile.open(artifact, "w", dereference=False) as archive:
                for child in sorted(fixed.store_path.iterdir(), key=lambda p: p.name):
                    archive.add(child, arcname=child.name, recursive=True)
        work = tmp / "work"
        work.mkdir()
        (work / "build.zig").touch()
        cache = tmp / "cache"
        cache.mkdir()
        (cache / "tmp").mkdir()
        result = run([zig, "fetch", "--global-cache-dir", str(cache), str(artifact)], cwd=work)
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        actual = lines[-1] if lines else ""
        if actual != expected:
            raise RuntimeError(f"Zig hash mismatch for {fixed.url}: expected {expected}, got {actual or '<empty>'}")
        arch = cache / "p" / f"{expected}.tar.gz"
        if not arch.is_file():
            raise RuntimeError(f"Zig did not create cache archive {arch}")
        extracted = tmp / "normalized"
        extracted.mkdir()
        with tarfile.open(arch, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        pkg = extracted / expected
        if not pkg.is_dir():
            raise RuntimeError(f"Zig cache archive has no {expected}/ root")
        return _scan_manifest(pkg / "build.zig.zon", pkg)


def _render_sources(sources: dict[str, FixedSource]) -> str:
    lines = ["# generated by tools/pipeline.py lock; do not edit by hand",
             "", "{ fetchgit, fetchurl, fetchzip }:", "", "{"]
    for zh in sorted(sources):
        src = sources[zh]
        lines.append(f"  {nix_string(zh)} = {{")
        if src.kind == "git":
            if not src.rev:
                raise AssertionError(f"git source {zh} has no immutable revision")
            lines += [
                "    source = fetchgit {",
                f"      url = {nix_string(src.url)};",
                f"      rev = {nix_string(src.rev)};",
                "      fetchSubmodules = false;",
                f"      hash = {nix_string(src.nix_hash)};",
                "    };",
            ]
        else:
            lines += [
                "    source = fetchurl {",
                f"      url = {nix_string(src.url)};",
                f"      hash = {nix_string(src.nix_hash)};",
                "    };",
                "    sourceIsArchive = true;",
            ]
        lines.append("  };")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


LOCK_ARGS = """args@{
  fetchgit, fetchurl, fetchzip, gnutar, lib, linkFarm, runCommandLocal, zig,
}:
"""


def _render_lock(hashes: Iterable[str]) -> str:
    lines = ["# generated by tools/pipeline.py lock; do not edit by hand",
             LOCK_ARGS.rstrip(), "",
             "(import ./mk-lock.nix args) ["]
    lines.extend(f"  {nix_string(h)}" for h in sorted(hashes))
    lines.append("]")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


def _committed_lock_hashes(repo: str, output: Path) -> set[str]:
    lock = output / f"{repo}.nix"
    if not lock.is_file():
        raise FileNotFoundError(f"missing committed lock for {repo}: {lock}")
    m = re.search(r"\(import\s+\./mk-lock\.nix\s+args\)\s*\[(.*?)\]", lock.read_text(), re.DOTALL)
    if not m:
        raise ValueError(f"legacy or malformed committed lock for {repo}: {lock}")
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _check_root_dependencies(root_specs: dict[str, set[str]], output: Path) -> None:
    errors: list[str] = []
    for repo, required in sorted(root_specs.items()):
        try:
            committed = _committed_lock_hashes(repo, output)
        except (FileNotFoundError, ValueError) as e:
            errors.append(str(e))
            continue
        missing = required - committed
        if missing:
            errors.append(f"{repo}: committed lock is missing root dependencies: " + ", ".join(sorted(missing)))
    if errors:
        raise RuntimeError("committed Zig locks are stale:\n  - " + "\n  - ".join(errors))


def cmd_lock(args: argparse.Namespace) -> int:
    repositories = _parse_repositories()
    local_root = args.source_root.resolve() if args.source_root else None
    root_specs: dict[str, set[str]] = {}
    specs: dict[str, DependencySpec] = {}

    for repo, pin in repositories:
        if local_root is not None:
            src = (local_root / repo).resolve()
        else:
            src = npins_get_path(pin)
        if not (src / "build.zig.zon").is_file():
            raise FileNotFoundError(f"missing build.zig.zon for {repo}: {src}")
        deps = _scan_manifest(src / "build.zig.zon", src)
        root_specs[repo] = {d.zig_hash for d in deps}
        for dep in deps:
            _add_spec(specs, dep)

    print("Root dependency inventory:")
    for repo in sorted(root_specs):
        print(f"  {repo}: {len(root_specs[repo])}")
        for zh in sorted(root_specs[repo]):
            print(f"    {zh}: {specs[zh].url}")

    output = args.output_dir.resolve()
    if args.check:
        _check_root_dependencies(root_specs, output)
        print(f"Committed root dependency locks are current for {len(root_specs)} repositories.")
        return 0
    if args.inventory_only:
        return 0

    zig = shutil.which(args.zig)
    if zig is None:
        raise FileNotFoundError(f"cannot find Zig executable: {args.zig}")
    ver = run([zig, "version"]).stdout.strip()
    if ver != "0.16.0":
        raise RuntimeError(f"lock generation requires Zig 0.16.0 exactly, found {ver or '<unknown>'}")

    sources: dict[str, FixedSource] = {}
    children: dict[str, set[str]] = {}
    resolved: dict[str, set[str]] = {}

    def resolve(zh: str) -> set[str]:
        if zh in resolved:
            return resolved[zh]
        if zh not in sources:
            spec = specs[zh]
            print(f"Prefetching {zh}", flush=True)
            fixed = _prefetch(spec)
            remote_children = _validate_and_scan(zig, fixed, zh)
            sources[zh] = fixed
            child_hashes: set[str] = set()
            for child in remote_children:
                _add_spec(specs, child)
                child_hashes.add(child.zig_hash)
            children[zh] = child_hashes
        closure = {zh}
        for ch in children.get(zh, set()):
            closure.update(resolve(ch))
        resolved[zh] = closure
        return closure

    closures: dict[str, set[str]] = {}
    for repo in sorted(root_specs):
        cl: set[str] = set()
        for zh in root_specs[repo]:
            cl.update(resolve(zh))
        closures[repo] = cl

    _atomic_write(output / "sources.nix", _render_sources(sources))
    for repo, hashes in closures.items():
        _atomic_write(output / f"{repo}.nix", _render_lock(hashes))

    expected = {f"{repo}.nix" for repo in closures}
    for lock_file in output.glob("otter-*.nix"):
        if lock_file.name not in expected and lock_file.read_text().startswith("# generated by tools/pipeline.py lock;"):
            lock_file.unlink()

    print(f"Generated {len(closures)} locks with {len(sources)} unique remote packages.")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: check
# ---------------------------------------------------------------------------

def _check_framework() -> None:
    repos_text = (ROOT / "nix/repositories.nix").read_text()
    specs_text = (ROOT / "nix/package-specs.nix").read_text()
    packages_text = (ROOT / "nix/packages.nix").read_text()
    maps_text = (ROOT / "nix/lib/dependency-maps.nix").read_text()
    fixups_text = (ROOT / "nix/lib/package-source-fixups.nix").read_text()
    flake_text = (ROOT / "flake.nix").read_text()

    repos = set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', repos_text, re.MULTILINE))
    specs = set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', specs_text, re.MULTILINE))

    def block_for(name: str) -> str:
        m = re.search(rf'^\s*"{re.escape(name)}"\s*=\s*\{{(.*?)^\s*\}};', repos_text, re.MULTILINE | re.DOTALL)
        if not m:
            raise ValueError(name)
        return m.group(1)

    err: list[str] = []
    repo_pins: dict[str, str] = {}
    for repo in sorted(repos):
        pin_match = re.search(r'\bpin\s*=\s*"([^"]+)";', block_for(repo))
        if pin_match:
            repo_pins[repo] = pin_match.group(1)
        else:
            err.append(f"repository metadata has no source pin: {repo}")

    for s in sorted(specs - repos):
        err.append(f"package spec without repository metadata: {s}")

    graph: dict[str, list[str]] = {}
    for repo in repos:
        block = block_for(repo)
        dm = re.search(r"directDeps = \[([^]]*)\];", block)
        graph[repo] = re.findall(r'"(otter-[^"]+)"', dm.group(1) if dm else "")

    for repo, deps in sorted(graph.items()):
        for dep in deps:
            if dep not in repos:
                err.append(f"unknown local dependency from {repo}: {dep}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(repo: str, stack: list[str]) -> None:
        if repo in visiting:
            err.append("dependency cycle: " + " -> ".join(stack + [repo]))
            return
        if repo in visited:
            return
        visiting.add(repo)
        for dep in graph[repo]:
            visit(dep, stack + [repo])
        visiting.remove(repo)
        visited.add(repo)

    for repo in sorted(repos):
        visit(repo, [])

    remote_repos = {repo for repo in repos if "hasRemoteDeps = true;" in block_for(repo)}
    lock_sources_path = ROOT / "locks/sources.nix"
    if lock_sources_path.is_file():
        source_hashes = set(re.findall(r'^\s*"([^"]+)"\s*=\s*\{', lock_sources_path.read_text(), re.MULTILINE))
    else:
        source_hashes = set()
        err.append("missing locks/sources.nix")

    missing_lock_sources: dict[str, set[str]] = {}
    for repo in sorted(remote_repos):
        lock_path = ROOT / f"locks/{repo}.nix"
        if not lock_path.is_file():
            err.append(f"missing Zig lock: {repo}")
            continue
        lock_text = lock_path.read_text()
        closure = re.search(r"\(import\s+\./mk-lock\.nix\s+args\)\s*\[(.*?)\]", lock_text, re.DOTALL)
        if not closure:
            err.append(f"legacy or malformed Zig lock: {repo}")
            continue
        lock_hashes = set(re.findall(r'"([^"]+)"', closure.group(1)))
        if not lock_hashes:
            err.append(f"empty Zig lock for repository with remote dependencies: {repo}")
        for zh in lock_hashes - source_hashes:
            missing_lock_sources.setdefault(zh, set()).add(repo)

    for zh, owners in sorted(missing_lock_sources.items()):
        err.append(f"Zig lock source missing: {zh} (required by {', '.join(sorted(owners))})")

    known_libraries = set(re.findall(r'(?<![A-Za-z0-9_.+-])"?([A-Za-z0-9_.+-]+)"?\s*=\s*(?:\{|null)', maps_text))
    used_libraries: set[str] = set()
    for block in re.findall(r'systemLibraries = \[([^]]*)\];', repos_text):
        used_libraries.update(re.findall(r'"([^"]+)"', block))
    for lib in sorted(used_libraries - known_libraries):
        err.append(f"system library has no mapping in nix/lib/dependency-maps.nix: {lib}")

    def attrset_keys(text: str, binding: str) -> set[str]:
        m = re.search(rf"\b{re.escape(binding)}\s*=\s*\{{(.*?)^\s*\}};", text, re.MULTILINE | re.DOTALL)
        if not m:
            err.append(f"missing attribute set in nix/lib/dependency-maps.nix: {binding}")
            return set()
        return set(re.findall(r'^\s*"?([A-Za-z0-9_.+-]+)"?\s*=', m.group(1), re.MULTILINE))

    for field, binding in (("runtimeTools", "runtimeToolMap"), ("nativeTools", "nativeToolMap")):
        used: set[str] = set()
        for body in re.findall(rf"\b{field}\s*=\s*\[([^]]*)\];", specs_text):
            used.update(re.findall(r'"([^"]+)"', body))
        missing = used - attrset_keys(maps_text, binding)
        for tool in sorted(missing):
            err.append(f"{field} entry has no {binding} mapping: {tool}")

    allowed_tiers = {"core", "helpers", "tools", "optional", "extras", "system"}
    used_tiers = set(re.findall(r'\btier\s*=\s*"([^"]+)";', specs_text))
    for tier in sorted(used_tiers - allowed_tiers):
        err.append(f"unknown package tier: {tier}")

    analysis_path = ROOT / "SOURCE-ANALYSIS.json"
    if analysis_path.is_file():
        try:
            analysis = json.loads(analysis_path.read_text())
        except json.JSONDecodeError as e:
            err.append(f"invalid SOURCE-ANALYSIS.json: {e}")
            analysis = {}
        if set(analysis.get("repositories", {})) != repos:
            err.append("SOURCE-ANALYSIS.json repository set is stale")
        if set(analysis.get("packages", [])) != specs:
            err.append("SOURCE-ANALYSIS.json package set is stale")
    else:
        err.append("missing SOURCE-ANALYSIS.json")

    required_files = [
        ".github/workflows/check.yml", ".gitignore", "LICENSE", "MANIFEST.sha256",
        "README.md", "MAINTENANCE.md", "VALIDATION.md", "SOURCE-ANALYSIS.json",
        "flake.nix", "flake.lock", "DESIGN.md",
        "examples/configuration.nix", "examples/consumer-flake.nix", "examples/home.nix",
        "modules/home-manager/default.nix", "modules/nixos/default.nix",
        "nix/repositories.nix", "nix/package-specs.nix", "nix/packages.nix",
        "nix/cuda-driver-abi.h", "nix/sources.nix",
        "nix/lib/graph.nix", "nix/lib/mk-workspace.nix", "nix/lib/mk-zig-package.nix",
        "nix/lib/source-info.nix", "nix/lib/dependency-maps.nix", "nix/lib/package-source-fixups.nix",
        "npins/default.nix", "npins/sources.json",
        "tools/pipeline.py",
        "locks/mk-cache-entry.nix", "locks/mk-lock.nix", "locks/sources.nix",
    ]
    for path in required_files:
        if not (ROOT / path).exists():
            err.append(f"missing required file: {path}")

    # npins pin validation
    pins_path = ROOT / "npins/sources.json"
    pins: dict[str, object] = {}
    if pins_path.is_file():
        try:
            pins_doc = json.loads(pins_path.read_text())
        except json.JSONDecodeError as e:
            err.append(f"invalid npins/sources.json: {e}")
        else:
            raw_pins = pins_doc.get("pins")
            if isinstance(raw_pins, dict):
                pins = raw_pins
            else:
                err.append("npins/sources.json has no pins object")

    extra_pins = set(re.findall(r'\bpin\s*=\s*"([^"]+)";', specs_text))
    required_pins = set(repo_pins.values()) | extra_pins | {"ghostty"}
    for pin_name in sorted(required_pins - pins.keys()):
        err.append(f"required source has no npins pin: {pin_name}")

    def is_local_reference(value: str) -> bool:
        normalized = value.replace("\\", "/").lower()
        return (normalized.startswith(("file:", "git+file:", "path:", "./", "../", "/", "repos/"))
                or normalized == "repos"
                or bool(re.match(r"^[a-z]:/", normalized)))

    def iter_strings(value: object, path: str = "$"):
        out: list[tuple[str, str]] = []
        if isinstance(value, str):
            out.append((path, value))
        elif isinstance(value, dict):
            for k, v in value.items():
                out.extend(iter_strings(v, f"{path}.{k}"))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                out.extend(iter_strings(v, f"{path}[{i}]"))
        return out

    for pin_name in sorted(required_pins & pins.keys()):
        pin = pins[pin_name]
        if not isinstance(pin, dict):
            err.append(f"npins pin is not an object: {pin_name}")
            continue
        if pin.get("type") not in {"Git", "GitRelease"}:
            err.append(f"npins pin is not an immutable remote Git source: {pin_name}")
        revision = pin.get("revision")
        if not isinstance(revision, str) or not HEX_REV.fullmatch(revision):
            err.append(f"npins pin has no immutable revision: {pin_name}")
        nix_hash = pin.get("hash")
        if not isinstance(nix_hash, str) or not SRI_SHA256.fullmatch(nix_hash):
            err.append(f"npins pin has no valid SRI sha256 hash: {pin_name}")
        for fname, value in iter_strings(pin):
            if is_local_reference(value):
                err.append(f"npins pin contains a local source reference: {pin_name}.{fname}")

    coordinated_repos = sorted(repos - {"otter-hypr", "otter-examples"})
    coordinated_versions: dict[str, list[str]] = {}
    for repo in coordinated_repos:
        pin = pins.get(repo_pins.get(repo, ""))
        if not isinstance(pin, dict):
            continue
        version = pin.get("version")
        if not isinstance(version, str) or not version:
            err.append(f"coordinated Otter source has no release version: {repo}")
            continue
        coordinated_versions.setdefault(version, []).append(repo)
    if len(coordinated_versions) > 1:
        detail = "; ".join(f"{v}: {', '.join(sorted(o))}" for v, o in sorted(coordinated_versions.items()))
        err.append(f"coordinated Otter pins contain mixed release versions: {detail}")

    for repo, pin_name in sorted(repo_pins.items()):
        pin = pins.get(pin_name)
        if not isinstance(pin, dict):
            continue
        repo_data = pin.get("repository")
        if not isinstance(repo_data, dict):
            err.append(f"npins pin has no repository identity: {pin_name}")
            continue
        if repo_data.get("type") != "Forgejo":
            err.append(f"Otter source is not pinned from Forgejo: {repo}")
        if repo_data.get("server") != "https://git.pika-os.com/":
            err.append(f"Otter source has an unexpected Forgejo server: {repo}")
        if repo_data.get("owner") != "otter-shell" or repo_data.get("repo") != repo:
            err.append(f"Otter source pin identity does not match repository metadata: {repo}")

    flake_lock_path = ROOT / "flake.lock"
    if flake_lock_path.is_file():
        try:
            flake_lock = json.loads(flake_lock_path.read_text())
        except json.JSONDecodeError as e:
            err.append(f"invalid flake.lock: {e}")
        else:
            nodes = flake_lock.get("nodes", {})
            if isinstance(nodes, dict):
                root_node_name = flake_lock.get("root")
                root_node = nodes.get(root_node_name, {}) if root_node_name else {}
                nixpkgs_node_name = root_node.get("inputs", {}).get("nixpkgs")
                nixpkgs_node = nodes.get(nixpkgs_node_name, {}) if isinstance(nixpkgs_node_name, str) else {}
                locked = nixpkgs_node.get("locked", {})
                original = nixpkgs_node.get("original", {})
                if isinstance(locked, dict) and isinstance(original, dict):
                    if locked.get("type") == "path" or original.get("type") == "path":
                        err.append("flake.lock contains a local nixpkgs path input")
                    if locked.get("owner") != "NixOS" or locked.get("repo") != "nixpkgs":
                        err.append("flake.lock does not pin the expected NixOS/nixpkgs input")
                    if not HEX_REV.fullmatch(str(locked.get("rev", ""))):
                        err.append("flake.lock nixpkgs input has no immutable revision")
                    if not SRI_SHA256.fullmatch(str(locked.get("narHash", ""))):
                        err.append("flake.lock nixpkgs input has no valid SRI narHash")

    # Workflow checks
    workflow_path = ROOT / ".github/workflows/check.yml"
    if workflow_path.is_file():
        wf = workflow_path.read_text()
        wf_checks = {
            "contents: read": "GitHub workflow does not use read-only repository permissions",
            "tools/pipeline.py check compat": "GitHub workflow does not validate pinned upstream sources",
            "tools/pipeline.py lock --check": "GitHub workflow does not check committed Zig lock roots",
            "nix flake check": "GitHub workflow does not run the flake checks",
            "packages.aarch64-linux.otter-bar.drvPath": (
                "GitHub workflow does not evaluate"
                " a representative aarch64 package"
            ),
            "nix build .#otter-bar": "GitHub workflow does not build a representative package",
            ".#otter-term": "GitHub workflow does not build the Ghostty VT consumer",
        }
        for needle, message in wf_checks.items():
            if needle not in wf:
                err.append(message)
        for action in re.findall(r"^\s*-\s+uses:\s*([^#\s]+)", wf, re.MULTILINE):
            if action.startswith("./"):
                continue
            ref = action.rsplit("@", 1)[-1]
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                err.append(f"GitHub Action is not pinned to an immutable commit: {action}")

    gitignore_path = ROOT / ".gitignore"
    if gitignore_path.is_file():
        ignored = {
            l.strip() for l in gitignore_path.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("#")
        }
        for pattern in ("repos/", ".consumer-eval-*.nix"):
            if pattern not in ignored:
                err.append(f"release-only local artifact is not ignored: {pattern}")

    builder_text = (ROOT / "nix/lib/mk-zig-package.nix").read_text()
    cache_entry_text = (ROOT / "locks/mk-cache-entry.nix").read_text()
    module_text = (ROOT / "modules/nixos/default.nix").read_text()
    home_module_text = (ROOT / "modules/home-manager/default.nix").read_text()

    if 'ln -s ${externalDeps} "$ZIG_GLOBAL_CACHE_DIR/p"' not in builder_text:
        err.append("Zig package cache is not linked directly at $ZIG_GLOBAL_CACHE_DIR/p")
    if "--hard-dereference" not in cache_entry_text:
        err.append("Zig cache archives may contain hard-link entries unsupported by Zig")
    if "$ZIG_GLOBAL_CACHE_DIR/p/deps" in builder_text or '"$ZIG_GLOBAL_CACHE_DIR/p/deps"' in packages_text:
        err.append("obsolete zon2nix p/deps cache layout is present")
    if "dontUnpack = true" in builder_text:
        err.append("builder bypasses standard patch semantics with dontUnpack")
    has_post_patch = bool(re.search(r"\binherit\s+.*?\bpostPatch\b.*?;", builder_text, re.DOTALL))
    if not has_post_patch or "postPatch = sharedResourcePatch" not in packages_text:
        err.append("framework fixups are not applied through the standard postPatch hook")
    for flag in ("dontUseZigConfigure", "dontUseZigBuild", "dontUseZigCheck", "dontUseZigInstall"):
        if f"{flag} = true;" not in builder_text:
            err.append(f"custom Zig builder does not disable nixpkgs hook phase: {flag}")
    if "or pkgs.zig" in packages_text:
        err.append("fragile fallback to an arbitrary pkgs.zig is present")
    if "zon2nix" in flake_text:
        err.append("obsolete zon2nix package is still present in a development shell")
    if "security.polkit.enablePkexecWrapper" not in module_text:
        err.append("NixOS module does not enable the pkexec security wrapper")
    if "${pkgs.polkit}/bin/pkexec" in packages_text or "pkgs.polkit" in packages_text:
        err.append("pkexec must resolve through the NixOS security wrapper, not the store")
    if 'platforms = [ "x86_64-linux" ];' not in specs_text:
        err.append("otter-vox x86_64 platform restriction is missing")
    if "DejaVuSans.ttf" not in packages_text or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" not in packages_text:
        err.append("shared render font fallback patch is missing")
    if "invalid or placeholder font" not in packages_text:
        err.append("font package does not reject stripped/LFS placeholder files")
    if "b9789.tar.gz" not in packages_text and "b9789.tar.gz" not in fixups_text:
        err.append("otter-assist does not inject its exact llama.cpp b9789 source")
    if "${./cuda-driver-abi.h}" not in packages_text and "${../cuda-driver-abi.h}" not in fixups_text:
        err.append("otter-rec does not inject the committed CUDA driver ABI shim")
    if 'ghosttySource.outPath + "/nix/libghostty-vt.nix"' not in packages_text or "ghosttyVt" not in packages_text:
        err.append("pinned Ghostty VT recipe is not wired into package dependencies")
    if "'theme.decorations.' 'theme.csd.'" not in specs_text:
        err.append("otter-hypr titlebar theme compatibility patch is missing")
    if "assist.model" not in home_module_text or '"--model"' not in home_module_text:
        err.append("Home Manager does not require and pass an otter-assist model")
    if "pulse.enable = true;" not in module_text:
        err.append("NixOS module does not enable PipeWire PulseAudio compatibility for paplay")

    if err:
        print("framework validation failed:", file=sys.stderr)
        for e in err:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)

    print(f"framework metadata OK: {len(repos)} Zig repositories, {len(specs)} packaged applications")


SOURCE_COMPAT_EXPECTED: dict[str, tuple[str, ...]] = {
    "otter-assist/scripts/build-llama-static.sh": (
        'tag="b9789"',
        'git clone --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$llama"',
        'elif [ -d "$llama/.git" ]; then',
        "-march=x86-64-v3",
    ),
    "otter-assist/build.zig": ("/usr/lib/otter-assist/",),
    "otter-assist/src/main.zig": ("/usr/lib/otter-assist/",),
    "otter-assist/src/config.zig": ("/usr/lib/otter-assist/",),
    "otter-config-types/src/assist.zig": ("/usr/lib/otter-assist/",),
    "otter-config-types/src/root.zig": ("/usr/lib/otter-assist/",),
    "otter-hypr/src/draw.zig": (
        "theme.decorations.titlebar_bg_active",
        "theme.decorations.titlebar_bg_inactive",
        "theme.decorations.button_close_bg",
        "theme.decorations.titlebar_text_active",
    ),
    "otter-settings/src/app_config.zig": ("/usr/bin/tee",),
    "otter-rec/src/kms_client.zig": ('"setcap"', '"pkexec"'),
    "otter-rec/src/av.h": ("#include <libavutil/hwcontext_cuda.h>",),
    "otter-rec/src/gpu_bridge.h": ("#include <cuda.h>", "#include <cudaGL.h>",),
    "otter-transcribe/scripts/build-parakeet-static.sh": (
        'if [ ! -d "$vendor/.git" ]; then',
        'git clone https://github.com/mudler/parakeet.cpp "$vendor"',
        'git -C "$vendor" submodule update --init --recursive',
    ),
    "otter-theme/src/theme.zig": ("pub const CSD = struct", "csd: CSD = .{}"),
    "otter-render/src/font/resolve.zig": ("/usr/share/fonts/otter-shell/",),
    "otter-render/build.zig": ("break :blk fontconfig_c.createModule();",),
    "otter-render/vendor/zigimg/src/simd.zig": (
        "inline for (0..8) |i| res[i] = v[@as(u32, @bitCast(mask[i]))];",
    ),
    "otter-render/src/quad_renderer.zig": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/LiberationSans-Regular.ttf",
    ),
    "otter-render/src/text/system.zig": (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/LiberationSans-Regular.ttf",
    ),
    "otter-config-types/src/term.zig": (
        "/usr/share/fonts/otter-shell/",
        "paplay",
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
    ),
    "otter-term/src/app/metrics.zig": ("/usr/share/fonts/otter-shell/",),
    "otter-term/src/app/effects.zig": (
        "paplay",
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
    ),
    "otter-config-types/src/lock.zig": ("/usr/share/otter-shell/lock/otter-shell.png",),
    "otter-wayland/build.zig": (
        "const xkbcommon = b.addTranslateC(.{",
        "}).createModule();",
    ),
}

REMOTE_COMPAT_EXPECTED: dict[str, tuple[str, ...]] = {
    "ghostty/include/ghostty/vt/terminal.h": (
        "ghostty_terminal_compression_activity(",
    ),
    "ghostty/include/ghostty/vt/selection.h": (
        "ghostty_terminal_selection_format_alloc(",
        "GhosttyTerminalSelectionFormatOptions",
    ),
    "ghostty/nix/libghostty-vt.nix": (
        "../build.zig.zon.nix",
        '"-Demit-lib-vt=true"',
    ),
    "parakeet_cpp/CMakeLists.txt": (
        'if(BASH_EXECUTABLE AND EXISTS "${CMAKE_SOURCE_DIR}/scripts/apply_ggml_patches.sh")',
        "add_subdirectory(third_party/ggml)",
    ),
    "parakeet_cpp/third_party/ggml-patches/0001-ggml-cpu-fold-broadcast-iterations-in-llamafile_sgem.patch": (
        "diff --git",
    ),
    "parakeet_cpp/third_party/ggml-patches/0004-cuda-pad-grid-stride.patch": (
        "diff --git",
    ),
    "parakeet_cpp/third_party/ggml/CMakeLists.txt": (
        "project(",
    ),
}


def _check_compat(source_root: Path | None) -> None:
    # Run generate --check first
    gen_args = ["--check"]
    if source_root is not None:
        gen_args = ["--source-root", str(source_root)] + gen_args
    subprocess.run([sys.executable, __file__, "generate"] + gen_args, cwd=ROOT, check=True)

    class Resolver:
        def __init__(self, root: Path | None):
            self._root = root.resolve() if root is not None else None
            self._cache: dict[str, Path] = {}

        def resolve_one(self, name: str) -> Path:
            cached = self._cache.get(name)
            if cached is not None:
                return cached
            if self._root is not None:
                path = self._root / name
            else:
                path = npins_get_path(name.replace("-", "_"))
            self._cache[name] = path
            return path

    local = Resolver(source_root)
    remote = Resolver(None)

    err: list[str] = []
    for relative, needles in SOURCE_COMPAT_EXPECTED.items():
        repo, _, child = relative.partition("/")
        path = local.resolve_one(repo) / child
        if not path.is_file():
            err.append(f"missing compatibility target: {relative}")
            continue
        text = path.read_text()
        for needle in needles:
            if needle not in text:
                err.append(f"upstream assumption changed in {relative}: {needle!r}")

    for relative, needles in REMOTE_COMPAT_EXPECTED.items():
        repo, _, child = relative.partition("/")
        path = remote.resolve_one(repo) / child
        if not path.is_file():
            err.append(f"missing compatibility target: {relative}")
            continue
        text = path.read_text()
        for needle in needles:
            if needle not in text:
                err.append(f"upstream assumption changed in {relative}: {needle!r}")

    if source_root is not None:
        font_path = local.resolve_one("otter-render") / "fonts/DejaVuSans.ttf"
    else:
        font_path = npins_get_path("otter_render") / "fonts/DejaVuSans.ttf"
    if not font_path.is_file():
        err.append("otter-render/fonts/DejaVuSans.ttf is missing")

    if source_root is not None:
        vox_build = local.resolve_one("otter-vox") / "build.zig"
    else:
        vox_build = npins_get_path("otter_vox") / "build.zig"
    if not vox_build.is_file() or "-mavx2" not in vox_build.read_text():
        err.append("otter-vox AVX2 assumption changed; review its platform restriction")

    if err:
        print("source compatibility validation failed:")
        for e in err:
            print(f"  - {e}")
        raise SystemExit(1)

    total = len(SOURCE_COMPAT_EXPECTED) + len(REMOTE_COMPAT_EXPECTED)
    print(f"source compatibility OK: {total} source-level assumptions")


def _check_manifest(write: bool = False) -> None:
    manifest_path = ROOT / "MANIFEST.sha256"
    ENTRY = re.compile(r"^([0-9a-f]{64})  \./([^\0\r\n]+)$")

    def tracked_files() -> set[str] | None:
        result = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        if result.returncode != 0:
            return None
        return {p.decode("utf-8") for p in result.stdout.split(b"\0") if p and p.decode("utf-8") != "MANIFEST.sha256"}

    tracked = tracked_files()

    if write:
        if tracked is None:
            raise SystemExit("cannot regenerate MANIFEST.sha256 outside a Git checkout")
        lines: list[str] = []
        for relative in sorted(tracked):
            file_path = ROOT / relative
            if not file_path.is_file():
                continue  # deleted from disk but still tracked by git
            if ".." in PurePosixPath(relative).parts:
                raise SystemExit(f"refusing unsafe tracked path: {relative}")
            digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            lines.append(f"{digest}  ./{relative}")
        tmp = manifest_path.with_name("MANIFEST.sha256.tmp")
        tmp.write_text("\n".join(lines) + "\n")
        tmp.replace(manifest_path)
        print(f"regenerated release manifest: {len(lines)} checksums")
        return  # skip validation after write

    err: list[str] = []
    entries: dict[str, str] = {}

    if not manifest_path.is_file():
        raise SystemExit("release manifest is missing: MANIFEST.sha256")

    for line_num, line in enumerate(manifest_path.read_text().splitlines(), 1):
        m = ENTRY.fullmatch(line)
        if not m:
            err.append(f"MANIFEST.sha256:{line_num}: malformed entry")
            continue
        expected_hash, relative = m.groups()
        if ".." in PurePosixPath(relative).parts:
            err.append(f"MANIFEST.sha256:{line_num}: unsafe path: {relative}")
            continue
        if relative == "MANIFEST.sha256":
            err.append("MANIFEST.sha256 must not contain its own checksum")
            continue
        if relative in entries:
            err.append(f"MANIFEST.sha256 contains a duplicate path: {relative}")
            continue
        entries[relative] = expected_hash

    on_disk: set[str] = set()
    if tracked is None:
        print("warning: no Git checkout found; verifying listed hashes without coverage", file=sys.stderr)
    else:
        on_disk = {p for p in tracked if (ROOT / p).is_file()}
        for relative in sorted(on_disk - entries.keys()):
            err.append(f"tracked release file is missing from MANIFEST.sha256: {relative}")
        for relative in sorted(entries.keys() - tracked):
            err.append(f"manifest entry is not a tracked release file: {relative}")

    for relative, expected_hash in sorted(entries.items()):
        file_path = ROOT / relative
        if not file_path.is_file():
            err.append(f"manifest entry is missing from the checkout: {relative}")
            continue
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            err.append(f"release checksum mismatch: {relative}")

    if err:
        print("release manifest validation failed:", file=sys.stderr)
        for e in err:
            print(f"  - {e}", file=sys.stderr)
        raise SystemExit(1)

    coverage = f" and {len(on_disk)} tracked paths" if tracked is not None else ""
    print(f"release manifest OK: {len(entries)} checksums{coverage}")


def cmd_check(args: argparse.Namespace) -> int:
    if args.mode in ("all", "framework"):
        _check_framework()
    if args.mode in ("all", "compat"):
        _check_compat(args.source_root)
    if args.mode in ("all", "manifest"):
        _check_manifest()
    return 0


# ---------------------------------------------------------------------------
# Subcommand: pin — npins pin management
# ---------------------------------------------------------------------------

def _repos_from_specs() -> list[str]:
    text = (ROOT / "nix/package-specs.nix").read_text()
    return re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', text, re.MULTILINE)


def _repos_from_metadata() -> list[str]:
    text = (ROOT / "nix/repositories.nix").read_text()
    return re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', text, re.MULTILINE)


def cmd_pin(args: argparse.Namespace) -> int:
    if not (ROOT / "npins/default.nix").is_file():
        run(["npins", "init", "--bare"], cwd=ROOT)

    forge = "https://git.pika-os.com"
    org = "otter-shell"
    repos = [r for r in _repos_from_metadata() if r not in {"otter-examples", "otter-hypr"}]

    if args.pin_mode == "heads":
        for repo in repos:
            pin = repo.replace("-", "_")
            print(f"Pinning {repo} to main")
            run(["npins", "add", "--name", pin, "forgejo", forge, org, repo, "--branch", "main"], cwd=ROOT)
        run(["npins", "add", "--name", "parakeet_cpp", "git",
             "https://github.com/mudler/parakeet.cpp.git",
             "--branch", "master", "--submodules"], cwd=ROOT)
        run(["npins", "add", "--name", "ghostty", "git",
             "https://github.com/ghostty-org/ghostty.git",
             "--branch", "main"], cwd=ROOT)
        print("Pinned repository heads. Commit npins/sources.json after reviewing the revisions.")
    elif args.pin_mode == "release":
        tag = f"v{args.version.lstrip('v')}"
        for repo in repos:
            pin = repo.replace("-", "_")
            print(f"Pinning {repo} at {tag}")
            run(["npins", "add", "--name", pin, "forgejo", forge, org, repo, "--at", tag], cwd=ROOT)
        run(["npins", "add", "--name", "otter_hypr", "forgejo", forge, org, "otter-hypr", "--branch", "main"], cwd=ROOT)
        run(["npins", "add", "--name", "otter_examples",
             "forgejo", forge, org, "otter-examples",
             "--branch", "main"], cwd=ROOT)
        run(["npins", "add", "--name", "parakeet_cpp", "git",
             "https://github.com/mudler/parakeet.cpp.git",
             "--branch", "master", "--submodules"], cwd=ROOT)
        run(["npins", "add", "--name", "ghostty", "git",
             "https://github.com/ghostty-org/ghostty.git",
             "--branch", "main"], cwd=ROOT)
        print(f"Pinned coordinated Otter release {tag}.")
        print("Next: pipeline.py lock")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: audit — Forgejo API check
# ---------------------------------------------------------------------------

def cmd_audit(args: argparse.Namespace) -> int:
    api = "git.pika-os.com"
    path = "/api/v1/orgs/otter-shell/repos"
    upstream_repos: list[str] = []
    page = 1
    conn = http.client.HTTPSConnection(api, timeout=30)
    while True:
        conn.request("GET", f"{path}?limit=50&page={page}")
        resp = conn.getresponse()
        if resp.status != 200:
            raise SystemExit(f"Forgejo API returned HTTP {resp.status}")
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"Forgejo API returned invalid JSON: {e}") from e
        if not data:
            break
        for repo in data:
            name = repo.get("name", "")
            if isinstance(name, str) and name.startswith("otter-"):
                upstream_repos.append(name)
        page += 1
    conn.close()
    upstream = sorted(set(upstream_repos))

    generated = _repos_from_metadata()
    ignored = {"otter-zenith"}
    upstream_zig = sorted(set(upstream) - ignored)

    new_repos = sorted(set(upstream_zig) - set(generated))
    removed_repos = sorted(set(generated) - set(upstream_zig))

    status = 0
    if new_repos:
        print("Upstream repositories not represented in nix/repositories.nix:")
        for r in new_repos:
            print(f"  + {r}")
        status = 1
    if removed_repos:
        print("Generated repositories no longer present upstream:")
        for r in removed_repos:
            print(f"  - {r}")
        status = 1
    if status == 0:
        print("Upstream repository set matches the generated Zig repository graph.")
    return status


# ---------------------------------------------------------------------------
# Subcommand: update — full pipeline
# ---------------------------------------------------------------------------

def cmd_update(args: argparse.Namespace) -> int:
    # 1. Audit (warn only, not fatal)
    try:
        cmd_audit(args)
    except SystemExit as e:
        if e.code:
            print("audit warning: upstream drift detected, continuing", file=sys.stderr)
        else:
            print("upstream repository set matches")

    # 2. npins update
    pins = args.pin_names
    run(["npins", "update"] + (pins if pins else []), cwd=ROOT)

    # 3. Generate
    gen_args = argparse.Namespace(source_root=None, check=False)
    cmd_generate(gen_args)

    # 4. Lock
    lock_args = argparse.Namespace(
        source_root=None, output_dir=ROOT / "locks", zig="zig",
        inventory_only=False, check=False,
    )
    cmd_lock(lock_args)

    # 5. Check
    check_args = argparse.Namespace(source_root=None, mode="all", write=False)
    cmd_check(check_args)

    print("Update complete.")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="regenerate nix/repositories.nix + SOURCE-ANALYSIS.json")
    p_gen.add_argument("--source-root", type=Path, help="directory with otter-* repos (instead of npins)")
    p_gen.add_argument("--check", action="store_true", help="verify freshness without writing")

    p_lock = sub.add_parser("lock", help="regenerate Zig dependency locks")
    p_lock.add_argument("--source-root", type=Path)
    p_lock.add_argument("--output-dir", type=Path, default=ROOT / "locks")
    p_lock.add_argument("--zig", default="zig", help="Zig 0.16 executable")
    p_lock.add_argument("--inventory-only", action="store_true", help="list root deps without fetching")
    p_lock.add_argument("--check", action="store_true", help="verify committed locks without writing")

    p_check = sub.add_parser("check", help="run validations")
    p_check.add_argument("mode", nargs="?", default="all", choices=["framework", "compat", "manifest", "all"])
    p_check.add_argument("--source-root", type=Path)
    p_check.add_argument("--write", action="store_true", help="regenerate MANIFEST.sha256 (manifest mode)")

    p_pin = sub.add_parser("pin", help="npins pin management")
    p_pin_sub = p_pin.add_subparsers(dest="pin_mode", required=True)
    p_release = p_pin_sub.add_parser("release", help="pin all repos to a coordinated release tag")
    p_release.add_argument("version", help="release version (e.g. 0.11.44)")
    p_pin_sub.add_parser("heads", help="pin all repos to main branches")

    sub.add_parser("audit", help="check Forgejo API for new/removed repositories")

    p_update = sub.add_parser("update", help="full pipeline: audit → npins → generate → lock → check")
    p_update.add_argument("pin_names", nargs="*", help="specific pins to update (default: all)")

    args = parser.parse_args()

    commands = {
        "generate": cmd_generate,
        "lock": cmd_lock,
        "check": cmd_check,
        "pin": cmd_pin,
        "audit": cmd_audit,
        "update": cmd_update,
    }

    # Handle --write in check subcommand
    if args.command == "check" and args.write and args.mode in ("all", "manifest"):
        _check_manifest(write=True)

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
