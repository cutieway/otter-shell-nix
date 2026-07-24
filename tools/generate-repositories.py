#!/usr/bin/env python3
"""Regenerate repository facts from an Otter sibling workspace or npins.

This intentionally generates only facts. Packaging/service policy remains in
nix/package-specs.nix.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Repository:
    pin: str
    snapshotVersion: str
    minimumZigVersion: str
    directDeps: list[str]
    hasRemoteDeps: bool
    systemLibraries: list[str]


def quoted(text: str) -> str:
    return json.dumps(text)


def find_sources(source_root: Path | None) -> dict[str, Path]:
    if source_root is not None:
        return {
            path.name: path
            for path in sorted(source_root.glob("otter-*"))
            if path.is_dir() and (path / "build.zig.zon").is_file()
        }

    pins_file = ROOT / "npins/sources.json"
    if not pins_file.is_file():
        raise SystemExit(
            "npins/sources.json is missing; pass --source-root or run tools/pin-release.sh"
        )
    pins = json.loads(pins_file.read_text()).get("pins", {})

    def _resolve_npins(pin: str) -> Path | None:
        """Return npins store path for *pin*, falling back to nix builtin fetchers."""
        try:
            source = Path(
                subprocess.check_output(["npins", "get-path", pin], cwd=ROOT, text=True, timeout=120).strip()
            )
            if source.is_dir():
                return source
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pass
        # Fallback: use nix builtin fetchers when npins paths are not realized.
        pin_data = pins.get(pin)
        if not pin_data or not pin_data.get("url"):
            return None
        pin_type = pin_data.get("type", "")
        url = pin_data["url"]
        try:
            if pin_type in ("GitRelease", "Url", "MutableUrl"):
                # Omit hash — older Nix versions don't support the hash argument to
                # builtins.fetchTarball. Without a hash the fetch is still correct,
                # just not content-addressed for caching.
                # Use toString because fetchTarball may return a string or a set
                # depending on Nix version.
                expr = f'(toString (builtins.fetchTarball {{ url = "{url}"; }}))'
            elif pin_type == "Git":
                rev = pin_data.get("revision", "")
                expr = f'(builtins.fetchGit {{ url = "{url}"; rev = "{rev}"; }}).outPath'
            else:
                return None
            source = Path(
                subprocess.check_output(
                    ["nix", "eval", "--impure", "--raw", "--expr", expr],
                    cwd=ROOT, text=True, timeout=120,
                ).strip()
            )
            return source if source.is_dir() else None
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return None

    result: dict[str, Path] = {}
    for pin in sorted(pins):
        if not pin.startswith("otter_"):
            continue
        source = _resolve_npins(pin)
        if source is not None and (source / "build.zig.zon").is_file():
            result[pin.replace("_", "-")] = source
    return result


def first(pattern: str, text: str, path: Path) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise ValueError(f"could not parse {pattern!r} from {path}")
    return match.group(1)


def strip_zig_comments(text: str) -> str:
    """Remove Zig comments without treating the // in URLs as comments."""
    output: list[str] = []
    index = 0
    in_string = False
    block_depth = 0
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if block_depth:
            if current == "*" and following == "/":
                block_depth -= 1
                index += 2
            elif current == "/" and following == "*":
                block_depth += 1
                index += 2
            else:
                if current == "\n":
                    output.append(current)
                index += 1
            continue
        if not in_string and current == "/" and following == "/":
            newline = text.find("\n", index + 2)
            if newline < 0:
                break
            output.append("\n")
            index = newline + 1
            continue
        if not in_string and current == "/" and following == "*":
            block_depth = 1
            index += 2
            continue
        output.append(current)
        if current == '"' and (index == 0 or text[index - 1] != "\\"):
            in_string = not in_string
        index += 1
    return "".join(output)


def zon_urls(text: str) -> list[str]:
    return re.findall(r'\.url\s*=\s*"([^"]+)"', strip_zig_comments(text))


def otter_repo_from_url(url: str) -> str | None:
    match = re.match(
        r"^(?:git\+)?https://git\.pika-os\.com/otter-shell/"
        r"(otter-[A-Za-z0-9_-]+?)(?:\.git)?(?:[?#].*)?$",
        url,
    )
    return match.group(1) if match else None


def reachable_manifests(root: Path) -> list[Path]:
    """Follow in-repository .path dependencies without scanning build caches."""
    root = root.resolve()
    pending = [(root / "build.zig.zon").resolve()]
    seen: set[Path] = set()

    while pending:
        manifest = pending.pop()
        if manifest in seen or not manifest.is_file():
            continue
        seen.add(manifest)
        text = strip_zig_comments(manifest.read_text())
        for relative in re.findall(r'\.path\s*=\s*"([^"]+)"', text):
            child = (manifest.parent / relative).resolve()
            try:
                child.relative_to(root)
            except ValueError:
                # Sibling Otter repositories own their own remote locks.
                continue
            pending.append(child / "build.zig.zon")

    return sorted(seen)


def inspect_repo(name: str, path: Path) -> Repository:
    zon_path = path / "build.zig.zon"
    zon = zon_path.read_text()
    build = (path / "build.zig").read_text() if (path / "build.zig").is_file() else ""

    path_deps = re.findall(r'\.path\s*=\s*"\.\./(otter-[^/"]+)(?:/[^"]*)?"', zon)
    url_deps = [
        dependency
        for url in zon_urls(zon)
        if (dependency := otter_repo_from_url(url)) is not None
    ]
    deps = sorted(set(path_deps + url_deps))
    remote_urls = [
        url
        for nested_zon in reachable_manifests(path)
        for url in zon_urls(nested_zon.read_text())
        if otter_repo_from_url(url) is None
    ]
    libraries = sorted(set(re.findall(r'linkSystemLibrary\s*\(\s*"([^"]+)"', build)))
    return Repository(
        pin=name.replace("-", "_"),
        snapshotVersion=first(r'\.version\s*=\s*"([^"]+)"', zon, zon_path),
        minimumZigVersion=first(
            r'\.minimum_zig_version\s*=\s*"([^"]+)"', zon, zon_path
        ),
        directDeps=deps,
        hasRemoteDeps=bool(remote_urls),
        systemLibraries=libraries,
    )


def render_nix(repositories: dict[str, Repository]) -> str:
    lines = ["# Generated by tools/generate-repositories.py.", "{"]
    for name, repo in sorted(repositories.items()):
        deps = " ".join(quoted(dep) for dep in repo.directDeps)
        libs = " ".join(quoted(lib) for lib in repo.systemLibraries)
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        help="directory containing sibling otter-* repositories; defaults to npins pins",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail instead of writing when metadata differs"
    )
    args = parser.parse_args()

    paths = find_sources(args.source_root)
    repositories = {name: inspect_repo(name, path) for name, path in paths.items()}
    unknown = sorted(
        {dep for repo in repositories.values() for dep in repo.directDeps} - repositories.keys()
    )
    if unknown:
        raise SystemExit("missing sibling repositories: " + ", ".join(unknown))

    nix = render_nix(repositories)
    nix_path = ROOT / "nix/repositories.nix"
    if args.check:
        if not nix_path.is_file() or nix_path.read_text() != nix:
            raise SystemExit("nix/repositories.nix is stale; regenerate it")
    else:
        nix_path.write_text(nix)

    specs_text = (ROOT / "nix/package-specs.nix").read_text()
    packages = sorted(
        set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', specs_text, re.MULTILINE))
    )
    analysis = {
        "snapshot": Counter(
            r.snapshotVersion for r in repositories.values()
        ).most_common(1)[0][0],
        "repositories": {name: asdict(repo) for name, repo in sorted(repositories.items())},
        "packages": packages,
    }
    analysis_path = ROOT / "SOURCE-ANALYSIS.json"
    rendered_json = json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not analysis_path.is_file() or analysis_path.read_text() != rendered_json:
            raise SystemExit("SOURCE-ANALYSIS.json is stale; regenerate it")
    else:
        analysis_path.write_text(rendered_json)

    print(f"inspected {len(repositories)} Zig repositories and {len(packages)} package specs")


if __name__ == "__main__":
    main()
