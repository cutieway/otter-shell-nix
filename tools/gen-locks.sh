#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

[[ -f npins/default.nix ]] || {
  echo 'Run tools/pin-release.sh first.' >&2
  exit 1
}

exec python3 tools/generate-zig-locks.py "$@"
