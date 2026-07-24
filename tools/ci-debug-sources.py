#!/usr/bin/env python3
"""Debug script: investigate why find_sources() returns empty in CI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    pins_file = ROOT / "npins" / "sources.json"

    if not pins_file.is_file():
        print("ERROR: npins/sources.json not found!")
        sys.exit(1)

    pins = json.loads(pins_file.read_text()).get("pins", {})
    otter_pins = sorted(k for k in pins if k.startswith("otter_"))
    print(f"Found {len(otter_pins)} otter_ pins")

    if not otter_pins:
        all_pins = list(pins.keys())
        print(f"No otter_* pins found. All pin names: {all_pins[:10]}{'...' if len(all_pins) > 10 else ''}")
        sys.exit(1)

    print("\n=== Detailed npins get-path for first 5 pins ===")
    for pin_name in otter_pins[:5]:
        try:
            result = subprocess.run(
                ["npins", "get-path", pin_name],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            source_path = Path(result.stdout.strip())
            print(f"\nPin: {pin_name}")
            print(f"  stdout: {result.stdout.strip()!r}")
            print(f"  stderr: {result.stderr.strip()!r}")
            print(f"  returncode: {result.returncode}")
            print(f"  Path as resolved: {source_path}")
            print(f"  Path exists: {source_path.exists()}")
            print(f"  Path is_dir: {source_path.is_dir()}")
            if source_path.exists():
                children = sorted(source_path.iterdir())
                print(f"  Children: {[p.name for p in children[:10]]}{'...' if len(children) > 10 else ''}")
                print(f"  build.zig.zon exists: {(source_path / 'build.zig.zon').is_file()}")
                if (source_path / "build.zig.zon").is_file():
                    zon_lines = (source_path / "build.zig.zon").read_text().splitlines()[:5]
                    print(f"  build.zig.zon first lines: {zon_lines}")
            else:
                print(f"  resolved symlinks: {source_path.resolve()}")
                print(f"  resolved exists: {source_path.resolve().exists()}")
        except Exception as e:
            print(f"\nPin: {pin_name}")
            print(f"  ERROR: {type(e).__name__}: {e}")

    print("\n=== Npins environment ===")
    try:
        npins_version = subprocess.run(
            ["npins", "--version"], capture_output=True, text=True, timeout=10
        )
        print(f"  npins --version: {npins_version.stdout.strip()}")
    except Exception as e:
        print(f"  npins --version ERROR: {e}")

    print(f"\n=== Running directory info ===")
    print(f"  CWD: {Path.cwd()}")
    print(f"  ROOT: {ROOT}")
    print(f"  npins/sources.json exists: {pins_file.is_file()}")
    print(f"  npins/default.nix exists: {(ROOT / 'npins' / 'default.nix').is_file()}")

    print("\n=== Sources.json content (summary) ===")
    if pins:
        sample_pin = next(iter(pins.items()))
        print(f"  First pin: {sample_pin[0]}")
        print(f"  First pin keys: {list(sample_pin[1].keys())}")
        print(f"  First pin url: {sample_pin[1].get('url', 'N/A')[:80]}...")


if __name__ == "__main__":
    main()
