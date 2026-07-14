#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ -f npins/default.nix ]] || npins init --bare

mapfile -t repos < <(python3 - <<'PY'
from pathlib import Path
import re
text=Path('nix/repositories.nix').read_text()
for name in re.findall(r'^\s*"(otter-[^"]+)"\s*=\s*\{', text, re.M):
    print(name)
PY
)
for repo in "${repos[@]}"; do
  npins add --name "${repo//-/_}" forgejo \
    https://git.pika-os.com otter-shell "$repo" --branch main
done
npins add --name parakeet_cpp git https://github.com/mudler/parakeet.cpp.git --branch master --submodules
npins add --name ghostty git \
  https://github.com/ghostty-org/ghostty.git \
  --branch main
echo "Pinned repository heads. Commit npins/sources.json after reviewing the revisions."
