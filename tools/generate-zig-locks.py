#!/usr/bin/env python3
"""Generate recursive, Zig 0.16-compatible Nix dependency locks.

Unlike the released zon2nix versions, this understands the current ZON syntax,
walks local path dependencies (including vendored packages), follows remote
packages' own build.zig.zon files, and emits cache archives named exactly as
Zig 0.16 expects under ZIG_GLOBAL_CACHE_DIR/p.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Iterable
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
PIKA_PREFIX = "git+https://git.pika-os.com/otter-shell/"
HEX_REV = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


@dataclasses.dataclass(frozen=True)
class DependencySpec:
    zig_hash: str
    url: str


@dataclasses.dataclass
class FixedSource:
    kind: str
    url: str
    nix_hash: str
    store_path: Path
    rev: str | None = None


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def strip_comments(text: str) -> str:
    """Remove Zig line/block comments while preserving strings and offsets."""
    out: list[str] = []
    i = 0
    quote = False
    escaped = False
    line_comment = False
    block_depth = 0

    while i < len(text):
        char = text[i]
        pair = text[i : i + 2]

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


def dependency_structs(zon_file: Path) -> list[str]:
    text = strip_comments(zon_file.read_text())
    match = re.search(r"\.dependencies\s*=\s*\.\s*\{", text)
    if not match:
        return []
    opening = text.find("{", match.start())
    closing = matching_brace(text, opening)
    body = text[opening + 1 : closing]

    structs: list[str] = []
    cursor = 0
    field = re.compile(r"\.(?:[A-Za-z_][A-Za-z0-9_]*|@\"(?:\\.|[^\"])+\")\s*=\s*\.\s*\{")
    while cursor < len(body):
        match = field.search(body, cursor)
        if not match:
            break
        # Only accept fields at the dependency table's top level.
        prefix = body[: match.start()]
        if prefix.count("{") != prefix.count("}"):
            cursor = match.end()
            continue
        opening = body.find("{", match.start())
        closing = matching_brace(body, opening)
        structs.append(body[opening + 1 : closing])
        cursor = closing + 1
    return structs


def string_field(struct: str, name: str) -> str | None:
    match = re.search(rf"\.{re.escape(name)}\s*=\s*\"((?:\\.|[^\"])*)\"", struct)
    if not match:
        return None
    # ZON strings use the same escapes needed by these manifests as JSON.
    return json.loads(f'"{match.group(1)}"')


def scan_manifest(zon_file: Path, boundary: Path) -> list[DependencySpec]:
    """Read remotes reachable through this manifest's in-repository paths."""
    boundary = boundary.resolve()
    pending = [zon_file.resolve()]
    seen: set[Path] = set()
    result: list[DependencySpec] = []

    while pending:
        manifest = pending.pop()
        if manifest in seen or not manifest.is_file():
            continue
        seen.add(manifest)

        for struct in dependency_structs(manifest):
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
                # Sibling Otter repositories have their own lock ownership.
                continue
            pending.append(child / "build.zig.zon")

    return result


def parse_repositories() -> list[tuple[str, str]]:
    text = (ROOT / "nix/repositories.nix").read_text()
    blocks = re.finditer(
        r'^\s*"(otter-[^"]+)"\s*=\s*\{(.*?)^\s*\};',
        text,
        re.MULTILINE | re.DOTALL,
    )
    result: list[tuple[str, str]] = []
    for block in blocks:
        body = block.group(2)
        if "hasRemoteDeps = true;" not in body:
            continue
        pin = re.search(r'\bpin\s*=\s*"([^"]+)";', body)
        if not pin:
            raise ValueError(f"{block.group(1)} has no npins pin")
        result.append((block.group(1), pin.group(1)))
    return result


def source_path(repo: str, pin: str, local_root: Path | None) -> Path:
    if local_root is not None:
        path = (local_root / repo).resolve()
    else:
        path = Path(run(["npins", "get-path", pin], cwd=ROOT).stdout.strip()).resolve()
    if not (path / "build.zig.zon").is_file():
        raise FileNotFoundError(f"missing build.zig.zon for {repo}: {path}")
    return path


def url_quality(url: str) -> tuple[int, str]:
    if not url.startswith("git+"):
        return (0, url)
    fragment = unquote(url.rsplit("#", 1)[-1]) if "#" in url else ""
    if HEX_REV.fullmatch(fragment):
        return (0, url)
    if fragment not in {"main", "master", "HEAD"}:
        return (1, url)
    return (2, url)


def add_spec(specs: dict[str, DependencySpec], spec: DependencySpec) -> None:
    previous = specs.get(spec.zig_hash)
    if previous is None or url_quality(spec.url) < url_quality(previous.url):
        specs[spec.zig_hash] = spec


def flake_prefetch(reference: str) -> dict[str, str]:
    command = [
        "nix",
        "flake",
        "prefetch",
        "--json",
        "--extra-experimental-features",
        "nix-command flakes",
        reference,
    ]
    result = run(command, cwd=ROOT)
    return json.loads(result.stdout)


def archive_prefetch(url: str) -> dict[str, str]:
    command = [
        "nix",
        "store",
        "prefetch-file",
        "--json",
        "--extra-experimental-features",
        "nix-command",
        url,
    ]
    result = run(command, cwd=ROOT)
    return json.loads(result.stdout)


def resolve_git_revision(url: str, fragment: str) -> str:
    """Resolve a tag, branch, or full ref to an immutable Git object ID."""
    candidates = (
        (f"refs/tags/{fragment}^{{}}", f"refs/tags/{fragment}"),
        (f"refs/heads/{fragment}",),
        (fragment,),
    )
    failures: list[str] = []
    for refs in candidates:
        try:
            result = run(["git", "ls-remote", url, *refs], cwd=ROOT)
        except subprocess.CalledProcessError as error:
            failures.append(error.stderr.strip())
            continue
        matches = {
            remote_ref: revision
            for revision, remote_ref in (
                line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line
            )
        }
        for remote_ref in refs:
            if remote_ref in matches:
                return matches[remote_ref]
    detail = "\n".join(message for message in failures if message)
    suffix = f":\n{detail}" if detail else ""
    raise RuntimeError(f"could not resolve git ref {fragment!r} from {url}{suffix}")


def prefetch(spec: DependencySpec) -> FixedSource:
    if not spec.url.startswith("git+"):
        # Keep the exact downloaded bytes. Zig accepts archives with multiple
        # top-level entries (notably UCD.zip), while fetchzip/flake tarball
        # unpacking does not preserve that artifact.
        result = archive_prefetch(spec.url)
        return FixedSource(
            kind="archive",
            url=spec.url,
            nix_hash=result["hash"],
            store_path=Path(result["storePath"]),
        )

    raw = spec.url[4:]
    if "#" not in raw:
        raise ValueError(f"git dependency lacks a revision fragment: {spec.url}")
    base, fragment = raw.rsplit("#", 1)
    base = base.split("?", 1)[0]
    fragment = unquote(fragment)

    revision = fragment if HEX_REV.fullmatch(fragment) else resolve_git_revision(base, fragment)
    result = flake_prefetch(f"git+{base}?rev={revision}")
    return FixedSource(
        kind="git",
        url=base,
        rev=revision,
        nix_hash=result["hash"],
        store_path=Path(result["storePath"]),
    )


def validate_and_scan(
    zig: str, fixed: FixedSource, expected: str
) -> list[DependencySpec]:
    """Validate Zig's hash, then scan Zig's normalized cache archive."""
    with tempfile.TemporaryDirectory(prefix="otter-zig-lock-") as temporary:
        temp = Path(temporary)
        if fixed.kind == "archive":
            artifact = fixed.store_path
        else:
            artifact = temp / "source.tar"
            with tarfile.open(artifact, "w", dereference=False) as archive:
                for child in sorted(fixed.store_path.iterdir(), key=lambda path: path.name):
                    archive.add(child, arcname=child.name, recursive=True)
        work = temp / "work"
        work.mkdir()
        (work / "build.zig").touch()
        cache = temp / "cache"
        # Zig 0.16's ZIP path creates a temporary file beneath the requested
        # global cache and does not create the cache root itself.
        cache.mkdir()
        (cache / "tmp").mkdir()
        result = run(
            [zig, "fetch", "--global-cache-dir", str(cache), str(artifact)],
            cwd=work,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        actual = lines[-1] if lines else ""
        if actual != expected:
            raise RuntimeError(
                f"Zig hash mismatch for {fixed.url}: expected {expected}, got {actual or '<empty>'}"
            )
        expected_archive = cache / "p" / f"{expected}.tar.gz"
        if not expected_archive.is_file():
            raise RuntimeError(f"Zig did not create cache archive {expected_archive}")

        extracted = temp / "normalized"
        extracted.mkdir()
        with tarfile.open(expected_archive, "r:gz") as archive:
            archive.extractall(extracted, filter="data")
        package = extracted / expected
        if not package.is_dir():
            raise RuntimeError(f"Zig cache archive has no {expected}/ root")
        return scan_manifest(package / "build.zig.zon", package)


def nix_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_sources(sources: dict[str, FixedSource]) -> str:
    lines = [
        "# generated by tools/gen-locks.sh; do not edit by hand",
        "",
        "{ fetchgit, fetchurl, fetchzip }:",
        "",
        "{",
    ]
    for zig_hash in sorted(sources):
        source = sources[zig_hash]
        lines.append(f"  {nix_string(zig_hash)} = {{")
        if source.kind == "git":
            lines.append("    source = fetchgit {")
            lines.append(f"      url = {nix_string(source.url)};")
            if not source.rev:
                raise AssertionError(f"git source {zig_hash} has no immutable revision")
            lines.append(f"      rev = {nix_string(source.rev)};")
            lines.append("      fetchSubmodules = false;")
            lines.append(f"      hash = {nix_string(source.nix_hash)};")
            lines.append("    };")
        else:
            lines.append("    source = fetchurl {")
            lines.append(f"      url = {nix_string(source.url)};")
            lines.append(f"      hash = {nix_string(source.nix_hash)};")
            lines.append("    };")
            lines.append("    sourceIsArchive = true;")
        lines.append("  };")
        lines.append("")
    lines.append("}")
    return "\n".join(lines) + "\n"


LOCK_ARGUMENTS = """args@{
  fetchgit,
  fetchurl,
  fetchzip,
  gnutar,
  lib,
  linkFarm,
  runCommandLocal,
  zig,
}:

"""


def render_lock(hashes: Iterable[str]) -> str:
    lines = [
        "# generated by tools/gen-locks.sh; do not edit by hand",
        LOCK_ARGUMENTS.rstrip(),
        "",
        "(import ./mk-lock.nix args) [",
    ]
    lines.extend(f"  {nix_string(zig_hash)}" for zig_hash in sorted(hashes))
    lines.append("]")
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content)
    os.replace(temporary, path)


def committed_lock_hashes(repo: str, output: Path) -> set[str]:
    lock = output / f"{repo}.nix"
    if not lock.is_file():
        raise FileNotFoundError(f"missing committed lock for {repo}: {lock}")
    match = re.search(
        r"\(import\s+\./mk-lock\.nix\s+args\)\s*\[(.*?)\]",
        lock.read_text(),
        re.DOTALL,
    )
    if not match:
        raise ValueError(f"legacy or malformed committed lock for {repo}: {lock}")
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def check_root_dependencies(root_specs: dict[str, set[str]], output: Path) -> None:
    errors: list[str] = []
    for repo, required in sorted(root_specs.items()):
        try:
            committed = committed_lock_hashes(repo, output)
        except (FileNotFoundError, ValueError) as error:
            errors.append(str(error))
            continue
        missing = required - committed
        if missing:
            errors.append(
                f"{repo}: committed lock is missing root dependencies: "
                + ", ".join(sorted(missing))
            )
    if errors:
        raise RuntimeError("committed Zig locks are stale:\n  - " + "\n  - ".join(errors))


def generate(args: argparse.Namespace) -> int:
    repositories = parse_repositories()
    local_root = args.source_root.resolve() if args.source_root else None
    root_specs: dict[str, set[str]] = {}
    specs: dict[str, DependencySpec] = {}

    for repo, pin in repositories:
        source = source_path(repo, pin, local_root)
        dependencies = scan_manifest(source / "build.zig.zon", source)
        root_specs[repo] = {dependency.zig_hash for dependency in dependencies}
        for dependency in dependencies:
            add_spec(specs, dependency)

    print("Root dependency inventory:")
    for repo in sorted(root_specs):
        print(f"  {repo}: {len(root_specs[repo])}")
        for zig_hash in sorted(root_specs[repo]):
            print(f"    {zig_hash}: {specs[zig_hash].url}")

    output = args.output_dir.resolve()
    if args.check:
        check_root_dependencies(root_specs, output)
        print(f"Committed root dependency locks are current for {len(root_specs)} repositories.")
        return 0
    if args.inventory_only:
        return 0

    zig = shutil.which(args.zig)
    if zig is None:
        raise FileNotFoundError(f"cannot find Zig executable: {args.zig}")
    zig_version = run([zig, "version"]).stdout.strip()
    if zig_version != "0.16.0":
        raise RuntimeError(
            f"lock generation requires Zig 0.16.0 exactly, found {zig_version or '<unknown>'}"
        )

    sources: dict[str, FixedSource] = {}
    children: dict[str, set[str]] = {}
    resolving: set[str] = set()

    def resolve(zig_hash: str) -> set[str]:
        if zig_hash in resolving:
            return {zig_hash}
        if zig_hash not in sources:
            spec = specs[zig_hash]
            print(f"Prefetching {zig_hash}", flush=True)
            fixed = prefetch(spec)
            remote_children = validate_and_scan(zig, fixed, zig_hash)
            sources[zig_hash] = fixed

            child_hashes: set[str] = set()
            for child in remote_children:
                add_spec(specs, child)
                child_hashes.add(child.zig_hash)
            children[zig_hash] = child_hashes

        resolving.add(zig_hash)
        closure = {zig_hash}
        for child_hash in children.get(zig_hash, set()):
            closure.update(resolve(child_hash))
        resolving.remove(zig_hash)
        return closure

    closures: dict[str, set[str]] = {}
    for repo in sorted(root_specs):
        closure: set[str] = set()
        for zig_hash in root_specs[repo]:
            closure.update(resolve(zig_hash))
        closures[repo] = closure

    atomic_write(output / "sources.nix", render_sources(sources))
    for repo, hashes in closures.items():
        atomic_write(output / f"{repo}.nix", render_lock(hashes))

    expected_locks = {f"{repo}.nix" for repo in closures}
    for lock in output.glob("otter-*.nix"):
        if lock.name in expected_locks:
            continue
        if lock.read_text().startswith("# generated by tools/gen-locks.sh;"):
            lock.unlink()

    print(f"Generated {len(closures)} locks with {len(sources)} unique remote packages.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        help="read repositories from this directory instead of npins get-path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "locks",
        help="lock directory (default: %(default)s)",
    )
    parser.add_argument(
        "--zig",
        default="zig",
        help="Zig 0.16 executable used to verify package hashes (default: %(default)s)",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="print root remote dependencies without fetching or writing",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if a root remote dependency is absent from a committed lock; do not write",
    )
    return generate(parser.parse_args())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.rstrip(), file=sys.stderr)
        raise SystemExit(1)
