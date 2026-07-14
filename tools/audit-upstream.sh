#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
api='https://git.pika-os.com/api/v1/orgs/otter-shell/repos?limit=100'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

curl -fsSL "$api" \
  | jq -r '.[].name | select(startswith("otter-"))' \
  | sort -u > "$tmp/upstream"

python3 - <<'PY' | sort -u > "$tmp/generated"
from pathlib import Path
import re
text = Path("nix/repositories.nix").read_text()
for name in re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', text, re.M):
    print(name)
PY

# Meta/build orchestration repository, intentionally not represented as Zig source.
printf '%s\n' otter-zenith > "$tmp/ignored"
grep -Fvx -f "$tmp/ignored" "$tmp/upstream" > "$tmp/upstream-zig" || true

new="$(comm -23 "$tmp/upstream-zig" "$tmp/generated")"
removed="$(comm -13 "$tmp/upstream-zig" "$tmp/generated")"

status=0
if [[ -n "$new" ]]; then
  echo 'Upstream repositories not represented in nix/repositories.nix:'
  while IFS= read -r repository; do
    printf '  + %s\n' "$repository"
  done <<< "$new"
  status=1
fi
if [[ -n "$removed" ]]; then
  echo 'Generated repositories no longer present upstream:'
  while IFS= read -r repository; do
    printf '  - %s\n' "$repository"
  done <<< "$removed"
  status=1
fi
if [[ $status -eq 0 ]]; then
  echo 'Upstream repository set matches the generated Zig repository graph.'
fi
exit "$status"
