#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
tools/audit-upstream.sh
npins update "$@"
python3 tools/generate-repositories.py
tools/gen-locks.sh
python3 tools/check-source-compat.py
python3 tools/check-framework.py
