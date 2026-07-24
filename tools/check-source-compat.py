#!/usr/bin/env python3
"""Check pinned Otter sources for assumptions encoded by the Nix layer.

Run this before updating pins or after an upstream refactor. It deliberately
fails when a source-level workaround no longer matches, so maintainers review
rather than silently carrying a stale substitution.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED: dict[str, tuple[str, ...]] = {
    "otter-assist/scripts/build-llama-static.sh": (
        'tag="b9789"',
        'git clone --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$llama"',
        'elif [ -d "$llama/.git" ]; then',
        "-march=x86-64-v3",
    ),
    "otter-assist/build.zig": (
        "/usr/lib/otter-assist/",
    ),
    "otter-assist/src/main.zig": (
        "/usr/lib/otter-assist/",
    ),
    "otter-assist/src/config.zig": (
        "/usr/lib/otter-assist/",
    ),
    "otter-config-types/src/assist.zig": (
        "/usr/lib/otter-assist/",
    ),
    "otter-config-types/src/root.zig": (
        "/usr/lib/otter-assist/",
    ),
    "otter-hypr/src/draw.zig": (
        "theme.decorations.titlebar_bg_active",
        "theme.decorations.titlebar_bg_inactive",
        "theme.decorations.button_close_bg",
        "theme.decorations.titlebar_text_active",
    ),
    "otter-settings/src/app_config.zig": (
        "/usr/bin/tee",
    ),
    "otter-rec/src/kms_client.zig": (
        '"setcap"',
        '"pkexec"',
    ),
    "otter-rec/src/av.h": (
        "#include <libavutil/hwcontext_cuda.h>",
    ),
    "otter-rec/src/gpu_bridge.h": (
        "#include <cuda.h>",
        "#include <cudaGL.h>",
    ),
    "otter-transcribe/scripts/build-parakeet-static.sh": (
        'if [ ! -d "$vendor/.git" ]; then',
        'git clone https://github.com/mudler/parakeet.cpp "$vendor"',
        'git -C "$vendor" submodule update --init --recursive',
    ),
    "otter-theme/src/theme.zig": (
        "pub const CSD = struct",
        "csd: CSD = .{}",
    ),
    "otter-render/src/font/resolve.zig": (
        "/usr/share/fonts/otter-shell/",
    ),
    "otter-render/build.zig": (
        "break :blk fontconfig_c.createModule();",
    ),
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
    "otter-term/src/app/metrics.zig": (
        "/usr/share/fonts/otter-shell/",
    ),
    "otter-term/src/app/effects.zig": (
        "paplay",
        "/usr/share/sounds/freedesktop/stereo/bell.oga",
    ),
    "otter-config-types/src/lock.zig": (
        "/usr/share/otter-shell/lock/otter-shell.png",
    ),
    "otter-wayland/build.zig": (
        "const xkbcommon = b.addTranslateC(.{",
        "}).createModule();",
    ),
}

REMOTE_EXPECTED: dict[str, tuple[str, ...]] = {
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


class SourceResolver:
    """Resolve repository-relative paths from a workspace or npins pins."""

    def __init__(self, source_root: Path | None) -> None:
        self.source_root = source_root.resolve() if source_root is not None else None
        self._repositories: dict[str, Path] = {}

    def repository(self, name: str) -> Path:
        cached = self._repositories.get(name)
        if cached is not None:
            return cached

        if self.source_root is not None:
            source = self.source_root / name
        else:
            source = self._resolve_npins(name)

        resolved = source.resolve()
        self._repositories[name] = resolved
        return resolved

    def _resolve_npins(self, name: str) -> Path:
        """Resolve an npins source to a store path, with fallback to nix builtin fetchers."""
        pin = name.replace("-", "_")
        try:
            output = subprocess.check_output(
                ["npins", "get-path", pin],
                cwd=ROOT,
                stderr=subprocess.PIPE,
                text=True,
            ).strip()
            if output:
                path = Path(output)
                if path.is_dir():
                    return path
        except subprocess.CalledProcessError:
            pass

        # Fallback: use nix builtin fetchers when npins paths are not realized
        # in CI environments (same pattern as generate-repositories.py).
        pins_file = ROOT / "npins/sources.json"
        if not pins_file.is_file():
            raise SystemExit(f"npins/sources.json is missing, cannot resolve {name}")
        pins = json.loads(pins_file.read_text()).get("pins", {})
        pin_data = pins.get(pin)
        if not pin_data:
            raise SystemExit(f"no npins pin for {name} (pin: {pin})")

        url = pin_data.get("url")
        if url is None:
            # Construct archive URL from GitHub repository metadata (e.g. parakeet_cpp).
            repo = pin_data.get("repository", {})
            revision = pin_data.get("revision")
            if repo.get("type") == "GitHub" and revision:
                url = f"https://github.com/{repo['owner']}/{repo['repo']}/archive/{revision}.tar.gz"
            else:
                raise SystemExit(
                    f"cannot construct fetch URL for npins pin {pin}: "
                    f"type={pin_data.get('type')}, url=null, revision={revision!r}"
                )

        try:
            expr = f'(toString (builtins.fetchTarball {{ url = "{url}"; }}))'
            output = subprocess.check_output(
                ["nix", "eval", "--impure", "--raw", "--expr", expr],
                cwd=ROOT, text=True, timeout=120,
            ).strip()
            path = Path(output)
            if path.is_dir():
                return path
            raise SystemExit(f"fetched source {name} is not a directory: {path}")
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
            raise SystemExit(f"could not resolve npins source {pin}: {error}") from error

    def path(self, relative: str) -> Path:
        repository, separator, child = relative.partition("/")
        if not separator:
            raise ValueError(f"source path has no repository component: {relative}")
        return self.repository(repository) / child


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        help="directory containing sibling otter-* repositories; defaults to npins pins",
    )
    args = parser.parse_args()
    sources = SourceResolver(args.source_root)
    remote_sources = SourceResolver(None)

    repository_check = [
        sys.executable,
        str(ROOT / "tools/generate-repositories.py"),
        "--check",
    ]
    if args.source_root is not None:
        repository_check[2:2] = ["--source-root", str(args.source_root.resolve())]
    subprocess.run(repository_check, cwd=ROOT, check=True)

    errors: list[str] = []
    for relative, needles in EXPECTED.items():
        path = sources.path(relative)
        if not path.is_file():
            errors.append(f"missing compatibility target: {relative}")
            continue
        text = path.read_text()
        for needle in needles:
            if needle not in text:
                errors.append(f"upstream assumption changed in {relative}: {needle!r}")

    # Support sources are always resolved through npins, even when an optional
    # local Otter workspace is being inspected.
    for relative, needles in REMOTE_EXPECTED.items():
        path = remote_sources.path(relative)
        if not path.is_file():
            errors.append(f"missing compatibility target: {relative}")
            continue
        text = path.read_text()
        for needle in needles:
            if needle not in text:
                errors.append(f"upstream assumption changed in {relative}: {needle!r}")

    font = sources.path("otter-render/fonts/DejaVuSans.ttf")
    if not font.is_file():
        errors.append("otter-render/fonts/DejaVuSans.ttf is missing")

    vox_build = sources.path("otter-vox/build.zig")
    if not vox_build.is_file() or "-mavx2" not in vox_build.read_text():
        errors.append("otter-vox AVX2 assumption changed; review its platform restriction")

    if errors:
        print("source compatibility validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    count = len(EXPECTED) + len(REMOTE_EXPECTED)
    print(f"source compatibility OK: {count} source-level assumptions")


if __name__ == "__main__":
    main()
