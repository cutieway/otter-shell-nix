#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
repos_text = (root / "nix/repositories.nix").read_text()
specs_text = (root / "nix/package-specs.nix").read_text()
packages_text = (root / "nix/packages.nix").read_text()
flake_text = (root / "flake.nix").read_text()
repos = set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', repos_text, re.M))
specs = set(re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', specs_text, re.M))

def block_for(name: str) -> str:
    match = re.search(
        rf'^\s*"{re.escape(name)}"\s*=\s*\{{(.*?)^\s*\}};',
        repos_text,
        re.M | re.S,
    )
    if not match:
        raise ValueError(name)
    return match.group(1)

graph: dict[str, list[str]] = {}
for repo in repos:
    block = block_for(repo)
    dep_match = re.search(r'directDeps = \[([^]]*)\];', block)
    graph[repo] = re.findall(r'"(otter-[^"]+)"', dep_match.group(1) if dep_match else "")

errors: list[str] = []
repo_pins: dict[str, str] = {}
for repo in sorted(repos):
    pin_match = re.search(r'\bpin\s*=\s*"([^"]+)";', block_for(repo))
    if pin_match:
        repo_pins[repo] = pin_match.group(1)
    else:
        errors.append(f"repository metadata has no source pin: {repo}")

for spec in sorted(specs - repos):
    errors.append(f"package spec without repository metadata: {spec}")
for repo, deps in sorted(graph.items()):
    for dep in deps:
        if dep not in repos:
            errors.append(f"unknown local dependency from {repo}: {dep}")

visiting: set[str] = set()
visited: set[str] = set()
def visit(repo: str, stack: list[str]) -> None:
    if repo in visiting:
        errors.append("dependency cycle: " + " -> ".join(stack + [repo]))
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

# A lock file must name the complete expected Zig closure, and every expected
# hash must have a fixed-output source. This turns an unfinished regeneration
# into a clear release-check failure instead of a sandbox network attempt.
remote_repos = {
    repo for repo in repos if "hasRemoteDeps = true;" in block_for(repo)
}
lock_sources_path = root / "locks/sources.nix"
if lock_sources_path.is_file():
    source_hashes = set(
        re.findall(r'^\s*"([^"]+)"\s*=\s*\{', lock_sources_path.read_text(), re.M)
    )
else:
    source_hashes = set()
    errors.append("missing locks/sources.nix")

missing_lock_sources: dict[str, set[str]] = {}
for repo in sorted(remote_repos):
    lock_path = root / f"locks/{repo}.nix"
    if not lock_path.is_file():
        errors.append(f"missing Zig lock: {repo}")
        continue
    lock_text = lock_path.read_text()
    closure = re.search(
        r"\(import\s+\./mk-lock\.nix\s+args\)\s*\[(.*?)\]",
        lock_text,
        re.S,
    )
    if not closure:
        errors.append(f"legacy or malformed Zig lock: {repo}")
        continue
    lock_hashes = set(re.findall(r'"([^"]+)"', closure.group(1)))
    if not lock_hashes:
        errors.append(f"empty Zig lock for repository with remote dependencies: {repo}")
    for zig_hash in lock_hashes - source_hashes:
        missing_lock_sources.setdefault(zig_hash, set()).add(repo)

for zig_hash, owners in sorted(missing_lock_sources.items()):
    errors.append(
        f"Zig lock source missing: {zig_hash} "
        f"(required by {', '.join(sorted(owners))})"
    )

known_libraries = set(re.findall(r'(?<![A-Za-z0-9_.+-])"?([A-Za-z0-9_.+-]+)"?\s*=\s*(?:\{|null)', packages_text))
used_libraries: set[str] = set()
for block in re.findall(r'systemLibraries = \[([^]]*)\];', repos_text):
    used_libraries.update(re.findall(r'"([^"]+)"', block))
for library in sorted(used_libraries - known_libraries):
    errors.append(f"system library has no mapping in nix/packages.nix: {library}")

def attrset_keys(text: str, binding: str) -> set[str]:
    match = re.search(rf"\b{re.escape(binding)}\s*=\s*\{{(.*?)^\s*\}};", text, re.M | re.S)
    if not match:
        errors.append(f"missing attribute set in nix/packages.nix: {binding}")
        return set()
    return set(re.findall(r'^\s*"?([A-Za-z0-9_.+-]+)"?\s*=', match.group(1), re.M))

for field, binding in (("runtimeTools", "runtimeToolMap"), ("nativeTools", "nativeToolMap")):
    used: set[str] = set()
    for body in re.findall(rf"\b{field}\s*=\s*\[([^]]*)\];", specs_text):
        used.update(re.findall(r'"([^"]+)"', body))
    missing = used - attrset_keys(packages_text, binding)
    for tool in sorted(missing):
        errors.append(f"{field} entry has no {binding} mapping: {tool}")

allowed_tiers = {"core", "helpers", "tools", "optional", "extras", "system"}
used_tiers = set(re.findall(r'\btier\s*=\s*"([^"]+)";', specs_text))
for tier in sorted(used_tiers - allowed_tiers):
    errors.append(f"unknown package tier: {tier}")

analysis_path = root / "SOURCE-ANALYSIS.json"
if analysis_path.is_file():
    analysis = json.loads(analysis_path.read_text())
    if set(analysis.get("repositories", {})) != repos:
        errors.append("SOURCE-ANALYSIS.json repository set is stale")
    if set(analysis.get("packages", [])) != specs:
        errors.append("SOURCE-ANALYSIS.json package set is stale")
else:
    errors.append("missing SOURCE-ANALYSIS.json")

required = [
    ".github/workflows/check.yml",
    ".gitignore",
    "LICENSE",
    "MANIFEST.sha256",
    "README.md",
    "MAINTENANCE.md",
    "VALIDATION.md",
    "SOURCE-ANALYSIS.json",
    "flake.nix",
    "flake.lock",
    "DESIGN.md",
    "examples/configuration.nix",
    "examples/consumer-flake.nix",
    "examples/home.nix",
    "modules/home-manager/default.nix",
    "modules/nixos/default.nix",
    "nix/repositories.nix",
    "nix/package-specs.nix",
    "nix/packages.nix",
    "nix/cuda-driver-abi.h",
    "nix/sources.nix",
    "nix/lib/graph.nix",
    "nix/lib/mk-workspace.nix",
    "nix/lib/mk-zig-package.nix",
    "nix/lib/source-info.nix",
    "npins/default.nix",
    "npins/sources.json",
    "tools/audit-upstream.sh",
    "tools/check-framework.py",
    "tools/check-manifest.py",
    "tools/pin-release.sh",
    "tools/pin-heads.sh",
    "tools/update.sh",
    "tools/generate-repositories.py",
    "tools/check-source-compat.py",
    "tools/gen-locks.sh",
    "tools/generate-zig-locks.py",
    "locks/mk-cache-entry.nix",
    "locks/mk-lock.nix",
    "locks/sources.nix",
]
for path in required:
    if not (root / path).exists():
        errors.append(f"missing required file: {path}")

# Public builds must resolve entirely from immutable remote pins. Validate the
# committed pin metadata itself so a local-workspace escape hatch cannot make a
# developer check pass while a clean consumer checkout fails.
pins_path = root / "npins/sources.json"
pins: dict[str, object] = {}
if pins_path.is_file():
    try:
        pins_document = json.loads(pins_path.read_text())
    except json.JSONDecodeError as error:
        errors.append(f"invalid npins/sources.json: {error}")
    else:
        raw_pins = pins_document.get("pins")
        if isinstance(raw_pins, dict):
            pins = raw_pins
        else:
            errors.append("npins/sources.json has no pins object")

extra_pins = set(re.findall(r'\bpin\s*=\s*"([^"]+)";', specs_text))
required_pins = set(repo_pins.values()) | extra_pins | {"ghostty"}
for pin_name in sorted(required_pins - pins.keys()):
    errors.append(f"required source has no npins pin: {pin_name}")

immutable_revision = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
sri_sha256 = re.compile(r"^sha256-[A-Za-z0-9+/]{43}=$")

def iter_strings(value: object, path: str = "$"):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")

def is_local_reference(value: str) -> bool:
    normalized = value.replace("\\", "/")
    lowered = normalized.lower()
    return (
        lowered.startswith(("file:", "git+file:", "path:", "./", "../", "/"))
        or lowered == "repos"
        or lowered.startswith("repos/")
        or re.match(r"^[a-z]:/", lowered) is not None
    )

for pin_name in sorted(required_pins & pins.keys()):
    pin = pins[pin_name]
    if not isinstance(pin, dict):
        errors.append(f"npins pin is not an object: {pin_name}")
        continue
    if pin.get("type") not in {"Git", "GitRelease"}:
        errors.append(f"npins pin is not an immutable remote Git source: {pin_name}")
    revision = pin.get("revision")
    if not isinstance(revision, str) or not immutable_revision.fullmatch(revision):
        errors.append(f"npins pin has no immutable revision: {pin_name}")
    nix_hash = pin.get("hash")
    if not isinstance(nix_hash, str) or not sri_sha256.fullmatch(nix_hash):
        errors.append(f"npins pin has no valid SRI sha256 hash: {pin_name}")
    for field, value in iter_strings(pin):
        if is_local_reference(value):
            errors.append(f"npins pin contains a local source reference: {pin_name}{field[1:]}")

# All repositories in the coordinated release set must move together. The two
# intentional branch pins have independent version lines and are excluded.
coordinated_repos = sorted(repos - {"otter-hypr", "otter-examples"})
coordinated_versions: dict[str, list[str]] = {}
for repo in coordinated_repos:
    pin = pins.get(repo_pins.get(repo, ""))
    if not isinstance(pin, dict):
        continue
    version = pin.get("version")
    if not isinstance(version, str) or not version:
        errors.append(f"coordinated Otter source has no release version: {repo}")
        continue
    coordinated_versions.setdefault(version, []).append(repo)

if len(coordinated_versions) > 1:
    detail = "; ".join(
        f"{version}: {', '.join(sorted(owners))}"
        for version, owners in sorted(coordinated_versions.items())
    )
    errors.append(f"coordinated Otter pins contain mixed release versions: {detail}")

for repo, pin_name in sorted(repo_pins.items()):
    pin = pins.get(pin_name)
    if not isinstance(pin, dict):
        continue
    repository = pin.get("repository")
    if not isinstance(repository, dict):
        errors.append(f"npins pin has no repository identity: {pin_name}")
        continue
    if repository.get("type") != "Forgejo":
        errors.append(f"Otter source is not pinned from Forgejo: {repo}")
    if repository.get("server") != "https://git.pika-os.com/":
        errors.append(f"Otter source has an unexpected Forgejo server: {repo}")
    if repository.get("owner") != "otter-shell" or repository.get("repo") != repo:
        errors.append(f"Otter source pin identity does not match repository metadata: {repo}")

# The flake input lock is part of the public reproducibility boundary as well.
flake_lock_path = root / "flake.lock"
if flake_lock_path.is_file():
    try:
        flake_lock = json.loads(flake_lock_path.read_text())
    except json.JSONDecodeError as error:
        errors.append(f"invalid flake.lock: {error}")
    else:
        nodes = flake_lock.get("nodes", {})
        root_node_name = flake_lock.get("root")
        root_node = nodes.get(root_node_name, {}) if isinstance(nodes, dict) else {}
        nixpkgs_node_name = root_node.get("inputs", {}).get("nixpkgs")
        nixpkgs_node = nodes.get(nixpkgs_node_name, {}) if isinstance(nodes, dict) else {}
        locked = nixpkgs_node.get("locked", {})
        original = nixpkgs_node.get("original", {})
        if locked.get("type") == "path" or original.get("type") == "path":
            errors.append("flake.lock contains a local nixpkgs path input")
        if locked.get("owner") != "NixOS" or locked.get("repo") != "nixpkgs":
            errors.append("flake.lock does not pin the expected NixOS/nixpkgs input")
        if not immutable_revision.fullmatch(str(locked.get("rev", ""))):
            errors.append("flake.lock nixpkgs input has no immutable revision")
        if not sri_sha256.fullmatch(str(locked.get("narHash", ""))):
            errors.append("flake.lock nixpkgs input has no valid SRI narHash")

workflow_path = root / ".github/workflows/check.yml"
if workflow_path.is_file():
    workflow_text = workflow_path.read_text()
    workflow_requirements = {
        "contents: read": "GitHub workflow does not use read-only repository permissions",
        "tools/check-manifest.py": "GitHub workflow does not validate the release manifest",
        "tools/check-source-compat.py": "GitHub workflow does not validate pinned upstream sources",
        "tools/generate-zig-locks.py --check": "GitHub workflow does not check committed Zig lock roots",
        "nix flake check": "GitHub workflow does not run the flake checks",
        "packages.aarch64-linux.otter-bar.drvPath": "GitHub workflow does not evaluate a representative aarch64 package",
        "nix build .#otter-bar": "GitHub workflow does not build a representative package",
        ".#otter-term": "GitHub workflow does not build the Ghostty VT consumer",
    }
    for needle, message in workflow_requirements.items():
        if needle not in workflow_text:
            errors.append(message)
    for action in re.findall(r"^\s*-\s+uses:\s*([^#\s]+)", workflow_text, re.M):
        if action.startswith("./"):
            continue
        reference = action.rsplit("@", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{40}", reference):
            errors.append(f"GitHub Action is not pinned to an immutable commit: {action}")

gitignore_path = root / ".gitignore"
if gitignore_path.is_file():
    ignored = {
        line.strip()
        for line in gitignore_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for pattern in ("repos/", "repos.7z", "otter-shell-nix.zip", "otter-shell-nix.tar.gz", ".consumer-eval-*.nix"):
        if pattern not in ignored:
            errors.append(f"release-only local artifact is not ignored: {pattern}")

builder_text = (root / "nix/lib/mk-zig-package.nix").read_text()
module_text = (root / "modules/nixos/default.nix").read_text()
home_module_text = (root / "modules/home-manager/default.nix").read_text()

if 'ln -s ${externalDeps} "$ZIG_GLOBAL_CACHE_DIR/p"' not in builder_text:
    errors.append("Zig package cache is not linked directly at $ZIG_GLOBAL_CACHE_DIR/p")
if "$ZIG_GLOBAL_CACHE_DIR/p/deps" in builder_text or '"$ZIG_GLOBAL_CACHE_DIR/p/deps"' in packages_text:
    errors.append("obsolete zon2nix p/deps cache layout is present")
if "dontUnpack = true" in builder_text:
    errors.append("builder bypasses standard patch semantics with dontUnpack")
if not re.search(r"\binherit\s+.*?\bpostPatch\b.*?;", builder_text, re.S) or "postPatch = sharedResourcePatch" not in packages_text:
    errors.append("framework fixups are not applied through the standard postPatch hook")
for flag in ("dontUseZigConfigure", "dontUseZigBuild", "dontUseZigCheck", "dontUseZigInstall"):
    if f"{flag} = true;" not in builder_text:
        errors.append(f"custom Zig builder does not disable nixpkgs hook phase: {flag}")
if "or pkgs.zig" in packages_text:
    errors.append("fragile fallback to an arbitrary pkgs.zig is present")
if "zon2nix" in flake_text:
    errors.append("obsolete zon2nix package is still present in a development shell")
if "security.polkit.enablePkexecWrapper" not in module_text:
    errors.append("NixOS module does not enable the pkexec security wrapper")
if "${pkgs.polkit}/bin/pkexec" in packages_text or "pkgs.polkit" in packages_text:
    errors.append("pkexec must resolve through the NixOS security wrapper, not the store")
if 'platforms = [ "x86_64-linux" ];' not in specs_text:
    errors.append("otter-vox x86_64 platform restriction is missing")
if "DejaVuSans.ttf" not in packages_text or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" not in packages_text:
    errors.append("shared render font fallback patch is missing")
if "invalid or placeholder font" not in packages_text:
    errors.append("font package does not reject stripped/LFS placeholder files")
if "b9789.tar.gz" not in packages_text:
    errors.append("otter-assist does not inject its exact llama.cpp b9789 source")
if "${./cuda-driver-abi.h}" not in packages_text or "src/cuda_driver_abi.h" not in packages_text:
    errors.append("otter-rec does not inject the committed CUDA driver ABI shim")
if 'ghosttySource.outPath + "/nix/libghostty-vt.nix"' not in packages_text or "ghosttyVt" not in packages_text:
    errors.append("pinned Ghostty VT recipe is not wired into package dependencies")
if "'theme.decorations.' 'theme.csd.'" not in specs_text:
    errors.append("otter-hypr titlebar theme compatibility patch is missing")
update_path = root / "tools/update.sh"
if update_path.is_file() and "tools/audit-upstream.sh" not in update_path.read_text():
    errors.append("canonical update does not audit the live Forgejo repository set")
if "assist.model" not in home_module_text or '"--model"' not in home_module_text:
    errors.append("Home Manager does not require and pass an otter-assist model")
if "pulse.enable = true;" not in module_text:
    errors.append("NixOS module does not enable PipeWire PulseAudio compatibility for paplay")

if errors:
    print("framework validation failed:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    raise SystemExit(1)

print(f"framework metadata OK: {len(repos)} Zig repositories, {len(specs)} packaged applications")
