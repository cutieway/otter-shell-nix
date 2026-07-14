#!/usr/bin/env bash
set -euo pipefail

version="${1:-0.11.43}"
tag="v${version#v}"
forge="https://git.pika-os.com"
org="otter-shell"
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ ! -f npins/default.nix ]]; then
  npins init --bare
fi

mapfile -t repos < <(python3 - <<'PY'
from pathlib import Path
import re
text=Path('nix/repositories.nix').read_text()
for name in re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', text, re.M):
    if name not in {'otter-examples', 'otter-hypr'}:
        print(name)
PY
)

for repo in "${repos[@]}"; do
  pin="${repo//-/_}"
  printf 'Pinning %s at %s\n' "$repo" "$tag"
  npins add --name "$pin" forgejo "$forge" "$org" "$repo" --at "$tag"
done

# otter-hypr is not part of the coordinated 0.11.x release set in the supplied
# zenith metadata; follow main and let npins record the exact revision.
npins add --name otter_hypr forgejo "$forge" "$org" otter-hypr --branch main

# The examples repository has its own 0.0.x version line, so track main at the
# exact revision recorded by npins rather than pretending it shares the release.
npins add --name otter_examples forgejo "$forge" "$org" otter-examples --branch main

# otter-transcribe clones this during its upstream build; Nix pins it explicitly.
npins add --name parakeet_cpp git \
  https://github.com/mudler/parakeet.cpp.git \
  --branch master --submodules

# Otter consumes development libghostty-vt APIs. Ghostty ships the matching
# Nix recipe and Zig dependency lock, so pin the known-compatible source here.
npins add --name ghostty git \
  https://github.com/ghostty-org/ghostty.git \
  --branch main

echo "Pinned coordinated Otter release $tag."
echo "Next: tools/gen-locks.sh"
