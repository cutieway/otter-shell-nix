#!/usr/bin/env python3
"""Verify release-manifest coverage and checksums for a clean Git checkout."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "MANIFEST.sha256"
ENTRY = re.compile(r"^([0-9a-f]{64})  \./([^\0\r\n]+)$")


def tracked_files() -> set[str] | None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return None
    return {
        path.decode("utf-8")
        for path in result.stdout.split(b"\0")
        if path and path.decode("utf-8") != MANIFEST.name
    }


def write_manifest(tracked: set[str] | None) -> None:
    if tracked is None:
        raise SystemExit("cannot regenerate MANIFEST.sha256 outside a Git checkout")

    lines: list[str] = []
    for relative in sorted(tracked):
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"refusing unsafe tracked path: {relative}")
        file_path = ROOT / relative
        if not file_path.is_file():
            raise SystemExit(f"tracked release path is not a regular file: {relative}")
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        lines.append(f"{digest}  ./{relative}")

    temporary = MANIFEST.with_name(f"{MANIFEST.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(MANIFEST)
    print(f"regenerated release manifest: {len(lines)} checksums")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the manifest from tracked files before validating it",
    )
    args = parser.parse_args()

    errors: list[str] = []
    entries: dict[str, str] = {}

    tracked = tracked_files()
    if args.write:
        write_manifest(tracked)

    if not MANIFEST.is_file():
        raise SystemExit("release manifest is missing: MANIFEST.sha256")

    for line_number, line in enumerate(MANIFEST.read_text().splitlines(), 1):
        match = ENTRY.fullmatch(line)
        if not match:
            errors.append(f"MANIFEST.sha256:{line_number}: malformed entry")
            continue
        expected_hash, relative = match.groups()
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"MANIFEST.sha256:{line_number}: unsafe path: {relative}")
            continue
        if relative == MANIFEST.name:
            errors.append("MANIFEST.sha256 must not contain its own checksum")
            continue
        if relative in entries:
            errors.append(f"MANIFEST.sha256 contains a duplicate path: {relative}")
            continue
        entries[relative] = expected_hash

    if tracked is None:
        print(
            "warning: no Git checkout found; verifying listed hashes without coverage",
            file=sys.stderr,
        )
    else:
        for relative in sorted(tracked - entries.keys()):
            errors.append(f"tracked release file is missing from MANIFEST.sha256: {relative}")
        for relative in sorted(entries.keys() - tracked):
            errors.append(f"manifest entry is not a tracked release file: {relative}")

    for relative, expected_hash in sorted(entries.items()):
        file_path = ROOT / relative
        if not file_path.is_file():
            errors.append(f"manifest entry is missing from the checkout: {relative}")
            continue
        actual_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            errors.append(f"release checksum mismatch: {relative}")

    if errors:
        print("release manifest validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        raise SystemExit(1)

    coverage = f" and {len(tracked)} tracked paths" if tracked is not None else ""
    print(f"release manifest OK: {len(entries)} checksums{coverage}")


if __name__ == "__main__":
    main()
