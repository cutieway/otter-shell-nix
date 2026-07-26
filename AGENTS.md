# Otter Shell Nix — AI Agents

Read CONVENTIONS.md before any git or Nix operation.

## Project

Nix flake packaging the Otter Shell ecosystem (45 Zig repos — Sway/Hyprland/Niri compositor tools) into 33 NixOS derivations. All builds sandboxed, no network. Framework owns the full Zig configure/build/install cycle.

**Stack:** Nix / Python / Shell / Zig 0.16

## Commands

| Action | Command |
| -------- | --------- |
| Build | `nix build .#<package>` (e.g. `nix build .#otter-bar`) |
| Build all | `nix build .#otter-shell-all` |
| Test/Lint | `nix flake check` (framework validation + shellcheck) |
| Format | `nix fmt` |
| Dev shell | `nix develop` |
| Bootstrap | `nix develop .#bootstrap` |
| Preflight | `nix flake check` |
| Refresh pins | `./tools/pipeline.py update [pin ...]` |
| Generate | `./tools/pipeline.py generate` |
| Locks | `./tools/pipeline.py lock` |
| Validate | `./tools/pipeline.py check all` |
| Pin release | `./tools/pipeline.py pin release VERSION` |

## Architecture

```
flake.nix               # Entry: packages, overlay, modules, devShells, checks
nix/
  packages.nix          # Builder: workspace assembly, dep resolution
  package-specs.nix     # MANUAL — packaging policy (33 specs)
  repositories.nix      # GENERATED — dep graph, pin mappings
  sources.nix           # npins integration (lazy bootstrap)
  lib/                  # mk-zig-package, mk-workspace, graph, source-info
locks/                  # Zig dependency locks (generated)
modules/                # NixOS + Home Manager module
tools/                  # pipeline.py — generate, lock, check, pin, audit, update
patches/                # Downstream patches
examples/               # NixOS/Home Manager configs
npins/                  # Pin state (sources.json)
```

## Design Constraints

1. **Zig 0.16 mandatory.** No fallback. Pinned in both flake overlay and nixpkgs consumer.
2. **Two repo files, one generated.** `repositories.nix` = auto-generated from npins. `package-specs.nix` = hand-maintained. Never edit the generated one.
3. **Framework owns Zig phases.** `dontUseZig*` all disabled. Multi-repo workspace, patched `build.zig.zon`, `$ZIG_GLOBAL_CACHE_DIR` pointing at merged lock derivations.
4. **`--replace-fail` always.** Stale patterns must fail the build, not silently skip.
5. **Versions from npins metadata.** Tagged = drop leading `v`. Branch = `unstable-<8-char-revision>`.
6. **Lazy bootstrap.** Missing npins → stub derivations, not eval failure.
7. **Ghostty special case.** Zig 0.15, uses its own nix/build infra.

## Conventions

- **Underscore vs hyphen:** npins pins use `otter_bar`; packages use `otter-bar`.
- **Service model:** `service = true` in package-specs → systemd user service (`PartOf=graphical-session.target`).
- **Tier system:** core/helpers/tools/optional/extras/system — determines bundle membership and default enablement.
- **Platform filtering:** Bundles use `lib.meta.availableOn`, never exclude whole bundles per platform.
- **Missing sources:** `runCommand` stub with `MISSING_SOURCE` file, not eval failure.
- **Hard-link dereferencing:** Zig's tar rejects hard-links; use `--hard-dereference` in cache archives.
- **Wrap only `$out/bin` executables** with executable permissions. `pkexec` stays unwrapped (NixOS wrapper path).

## Agent Rules

- **Always Green:** Preflight must be green before forward work. Gate failures need fix-or-log per CONVENTIONS.md.
- Read `specs/` before writing code.
- All planning output goes to `specs/` (`product/`, `epics/`, `release-plan.yaml`, etc.).
- Write the minimum code that solves the problem. Ponytail-first: stdlib over deps, deletion over addition.
- Run tests after every change. Show evidence before declaring done.
