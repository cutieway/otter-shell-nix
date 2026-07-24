# Otter Shell Nix Framework

## Project overview

A Nix flake that packages Otter Shell -- a Wayland compositor environment built from 45 independent Forgejo-hosted Zig repositories -- into 33 application packages using Zig 0.16.0. The framework generates a central dependency graph from npins-pinned sources, produces recursive fixed-output Zig dependency locks, and provides NixOS and Home Manager modules for system integration. All builds run in a Nix sandbox with no network access; the framework owns the full Zig configure/build/install phase sequence rather than using nixpkgs' Zig setup hook.

## Build, test, lint commands

```bash
# Build a single package
nix build .#otter-bar

# Build aggregate bundles
nix build .#otter-shell-core
nix build .#otter-shell-extras
nix build .#otter-shell-system
nix build .#otter-shell-all

# Run full flake check (framework validation + shellcheck)
nix flake check

# Format all Nix files
nix fmt

# Enter dev shell (includes npins, zig_0_16, jq, curl, git, python3, shellcheck, nixfmt)
nix develop

# Bootstrap shell (minimal: no shellcheck or nixfmt)
nix develop .#bootstrap

# Framework validation (runs inside flake check, also manual)
python3 tools/check-framework.py

# Source compatibility assertions
python3 tools/check-source-compat.py

# Manifest integrity check
python3 tools/check-manifest.py

# Shellcheck all shell scripts
shellcheck tools/*.sh

# Regenerate repository metadata from npins
python3 tools/generate-repositories.py

# Regenerate all Zig dependency locks
python3 tools/generate-zig-locks.py
# Or via the shell wrapper (preferred):
./tools/gen-locks.sh

# Full pin refresh and regeneration
./tools/update.sh [pin-name ...]

# Coordinated release update
./tools/audit-upstream.sh
./tools/pin-release.sh <version>
./tools/generate-repositories.py
./tools/gen-locks.sh
python3 tools/check-source-compat.py
python3 tools/check-framework.py
nix flake check path:. --show-trace
```

## Architecture and code organization

```
flake.nix                    # Flake entry point: packages, overlay, modules, devShells, checks
flake.lock                   # nixpkgs pin (only flake input)
nix/
  packages.nix               # Main builder: workspace assembly, dependency resolution, per-package creation
  package-specs.nix          # Hand-written packaging policy (33 specs): executable, tier, service flags, extra deps
  repositories.nix           # GENERATED -- dependency graph, pin mappings, system libraries (45 repos)
  sources.nix                # npins integration: loads pins and sources lazily for bootstrap
  cuda-driver-abi.h          # Minimal CUDA driver ABI declarations for otter-rec (no unfree SDK)
  lib/
    mk-zig-package.nix       # Core derivation builder: unpack, cache setup, zig build/install/test
    mk-workspace.nix         # Creates a linkFarm workspace from closure of pinned sources
    graph.nix                # Transitive dependency closure computation + cycle detection
    source-info.nix          # Version derivation from npins pin metadata
locks/
  sources.nix                # GENERATED -- fixed-output fetchers for 17 external Zig sources
  mk-lock.nix                # Builds a merged lock derivation from Zig hash list
  mk-cache-entry.nix         # Converts a source into Zig 0.16 cache archive, verifying hash
  otter-*.nix                # Per-repository lock closures with Zig hash lists (generated)
modules/
  nixos/default.nix          # NixOS module: PipeWire, Polkit, PAM, fonts, rec KMS wrapper
  home-manager/default.nix   # Home Manager module: per-component enable, systemd services, sway integration
npins/
  sources.json               # Pin state (release tags + branch revisions)
  default.nix                # npins-generated source fetcher
tools/
  update.sh                  # Canonical refresh: audit, npins update, regenerate everything, check
  pin-release.sh             # Pin a coordinated release version across all repos
  pin-heads.sh               # Pin all repos to main branch heads (for development)
  gen-locks.sh               # Shell wrapper around generate-zig-locks.py
  audit-upstream.sh          # Check Forgejo API for new/removed repositories
  generate-repositories.py   # Scan npins sources and write repositories.nix + SOURCE-ANALYSIS.json
  generate-zig-locks.py      # Recursive Zig lock generator (replaces zon2nix for Zig 0.16)
  check-framework.py         # Structural validation: graph cycles, spec/repo consistency, lock completeness
  check-source-compat.py     # Assert exact upstream source literals expected by Nix substitutions
  check-manifest.py          # MANIFEST.sha256 integrity and file coverage validation
examples/                   # Example NixOS/Home Manager configurations
patches/                    # Downstream patches applied via standard derivation patch phase
```

## Coding style preferences

**Nix:**
- Format with `nixfmt` (not nixpkgs-fmt or alejandra) -- the formatter is pinned in flake.nix.
- Use `lib.genAttrs`, `lib.mapAttrs`, `lib.filterAttrs`, and `lib.optionalAttrs` for attribute set operations.
- Prefer `lib.optional` / `lib.optionalString` over inline `if ... then [ ... ] else [ ]` patterns.
- Use `lib.mkIf` for conditional config in modules, not inline conditionals.
- Escape variables in shell-in-Nix with `''${...}` (the `$` doubling convention).
- Use `substituteInPlace` with `--replace-fail` (not `--replace`) so stale substitutions fail loudly.
- Use `lib.escapeShellArg` / `lib.escapeShellArgs` for shell interpolation.
- Import paths are relative (e.g., `import ./lib/graph.nix`), never absolute.
- Pin attribute names in repositories.nix use underscore (e.g., `otter_bar`), matching npins convention.

**Python:**
- Type annotations (`from __future__ import annotations`) at top of every file.
- Use `pathlib.Path` for filesystem operations, never `os.path`.
- Dataclasses for structured data, typed as `frozen=True` where immutable.
- Consistent `ROOT = Path(__file__).resolve().parents[1]` pattern for project root.
- Shebang: `#!/usr/bin/env python3` for executable tools, no shebang for library-like scripts.
- Regex helpers extracted to small named functions or inline with `re.M | re.S`.
- Validation scripts accumulate errors in a list and exit non-zero at the end (never `sys.exit(1)` on first failure).

**Shell:**
- `set -euo pipefail` at top of every script.
- `root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"` for project root discovery.
- Prefer `mapfile` / `readarray` over looping with `for ... in $(...)`.
- Error messages prefixed with `otter-shell-nix:` for grep-ability.

## Key design decisions

See DESIGN.md for the full rationale, but the critical constraints are:

1. **Zig 0.16 is mandatory.** The framework requires exactly `zig_0_16` from the pinned nixpkgs; there is no fallback. Both the flake's overlay and the nixpkgs consumer pin establish this.
2. **Two repository files, one generated.** `nix/repositories.nix` is machine-generated from npins sources and contains dependency topology, pin mappings, and system library requirements. `nix/package-specs.nix` is hand-maintained and holds only packaging policy (executable names, tiers, service behavior, exceptional system deps, source patches). Never edit repositories.nix by hand.
3. **Framework owns Zig phases.** The `mkZigPackage` builder disables all four nixpkgs Zig setup hook switches (`dontUseZig*`). It creates a multi-repo workspace from the dependency closure, patches `build.zig.zon` URL deps to local paths, and sets up `$ZIG_GLOBAL_CACHE_DIR/p` pointing at a merged `buildEnv` of fixed-output lock derivations.
4. **All source substitutions use `--replace-fail`.** Stale substitutions must fail the build rather than silently continuing. Source compatibility assertions in `check-source-compat.py` match these substitutions exactly.
5. **Packages are built with the flake's pinned nixpkgs.** The overlay re-exports those derivations; it does not rebuild against a consumer's arbitrary Zig or nixpkgs version.
6. **Versions come from npins metadata.** Release pins (tagged) drop the leading `v`. Branch pins become `unstable-<8-char-revision>`.
7. **Lazy bootstrap.** Before npins initialization, `nix/sources.nix` returns empty sets, allowing `nix develop .#bootstrap` to work from scratch. The `pin-release.sh` script calls `npins init --bare` when needed.
8. **Ghostty is a special case.** It uses Zig 0.15 and ships its own `nix/libghostty-vt.nix` + `build.zig.zon.nix`. The framework calls those from the pinned revision rather than running Ghostty through the Otter Zig 0.16 lock generator.

## Common tasks

**Add a new Otter repository:**
1. Pin it with `npins add --name <pin_name> forgejo <forge_url> <org> <repo> [--at <tag> | --branch <branch>]`.
2. Regenerate repository metadata: `python3 tools/generate-repositories.py`.
3. If it installs a runnable program, add one entry in `nix/package-specs.nix`.
4. Add system libraries or native/runtime tools to the corresponding maps in `nix/packages.nix` only when needed.
5. Add source-level assertions to `tools/check-source-compat.py` for every Nix-specific substitution.
6. Generate locks: `./tools/gen-locks.sh`.
7. Build directly: `nix build .#<package-name>`.
8. Add to a default tier in `nix/packages.nix` bundle definition when stable.

**Update pins (routine):**
```bash
nix develop .#bootstrap
./tools/update.sh          # all pins, or
./tools/update.sh otter_bar otter_ui  # subset
nix flake check path:. --show-trace
```

**Coordinated release update:**
```bash
nix develop
./tools/audit-upstream.sh
./tools/pin-release.sh 0.11.44
./tools/generate-repositories.py
./tools/gen-locks.sh
python3 tools/check-source-compat.py
python3 tools/check-framework.py
nix flake check path:. --show-trace
```

**Fix a failed build:**
- Missing sibling path: regenerate repositories.nix; do not hand-copy deps.
- Zig tries the network: regenerate full lock set from npins.
- pkg-config can't find a library: add the real nixpkgs package to `systemDependencyMap` in packages.nix.
- Command not found at runtime: add a narrow `runtimeTools` entry in the package spec.
- Hardcoded `/usr` path: use `substituteInPlace --replace-fail` and assert the literal in check-source-compat.py.
- Patch no longer applies: inspect upstream change; remove stale workaround rather than weakening `--replace-fail`.
- Ghostty API mismatch: verify the Ghostty pin still exports the APIs asserted by check-source-compat.py.

**Release gate (run before publishing):**
```bash
python3 tools/check-source-compat.py
python3 tools/generate-zig-locks.py --check
python3 tools/check-framework.py
python3 tools/check-manifest.py
nix flake check
nix build .#otter-shell-core
nix build .#otter-shell-extras
nix build .#otter-shell-system
nix build .#otter-shell-all
```

Regenerate `MANIFEST.sha256` only after the release tree is final:
```bash
python3 tools/check-manifest.py --write
```

## Known conventions

- **Underscore vs hyphen:** npins pin names use underscores (`otter_bar`); repository/package names use hyphens (`otter-bar`). The mapping lives in `repositories.nix` and `source-info.nix`.
- **Service model:** Components with `service = true` in `package-specs.nix` get systemd user services via the Home Manager module. Services are `PartOf=graphical-session.target` with `Restart=on-failure`. The `serviceArgs` field adds extra CLI arguments to the unit's `ExecStart`.
- **Tier system:** Packages are classified as `core`, `helpers`, `tools`, `optional`, `extras`, or `system`. These determine which aggregate bundle includes them (core, extras, system, all). Default Home Manager enablement follows tier: core and helpers enabled by default; everything else opt-in.
- **Cross-platform filtering:** Individual packages remain visible on both `x86_64-linux` and `aarch64-linux`, but aggregate bundles use `lib.meta.availableOn` to filter platform-restricted packages (e.g., `otter-vox` x86_64-only). Never exclude an entire bundle per platform.
- **Missing source handling:** Sources are resolved from npins lazily. Missing sources produce a `runCommand` stub with a `MISSING_SOURCE` file, not an eval failure. Actual build failure happens only at derivation time.
- **Substitute safety:** All `substituteInPlace` calls use `--replace-fail` so stale patterns produce a hard error at build time rather than silently doing nothing.
- **Hard-link dereferencing:** When archiving sources for Zig cache entries, `--hard-dereference` is used because Zig's tar reader rejects hard-link records and Nix stores may deduplicate identical files.
- **Legacy wrapper model:** `runtimeTools` entries use `wrapProgram --prefix PATH` in `postFixup`. Only executables in `$out/bin` with executable permissions get wrapped. `pkexec` is intentionally not patched -- it must come from `/run/wrappers/bin/pkexec` on NixOS.
