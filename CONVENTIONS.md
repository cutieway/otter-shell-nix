# Otter Shell Nix — Conventions

Shared rules for all AI agents working on this project.

## Workflow

- **Always Green / Shift Left.** The 1-10-100 principle: a bug caught at Preflight costs 1x, at CI costs 10x, in production costs 100x. Preflight (`nix flake check`) and CI must be green before any forward work.
- **Discovered Defects.** If a broken test or lint error is discovered during planned work, follow the fix-or-log ladder: quick-fix (data-only, trivial) → fix-bug (needs investigation, logic change). Put fix commits in a separate commit from feature work.
- **Banned dismissive phrases.** Never wave away a red gate with:
  - "This was pre-existing"
  - "Unrelated to my changes"
  - "Not introduced by this session"
  - "Out of scope"
  
  A red gate is a red gate. Fix it or log a bug in `specs/bugs/`.

## Generated vs Manual

- **Strict separation.** Auto-generated files (pipeline outputs) live in `nix/repositories.nix`, `locks/otter-*.nix`, `locks/sources.nix`, `MANIFEST.sha256`. Never edit these by hand — they are produced by `tools/pipeline.py generate` and `tools/pipeline.py lock`.
- **Hand-maintained files.** `nix/package-specs.nix`, `nix/packages.nix`, `modules/`, `patches/`, `examples/`. These are the developer's domain.
- **No manual hash edits.** The pipeline owns all hashes. `--replace-fail` is non-negotiable — never weaken to `--replace`.
- **No network at build time.** Nix sandbox is enforced. All sources pinned via npins. All Zig dependencies locked via fixed-output derivations.

## Code quality

- **Ponytail-first.** Standard library before dependencies. Deletion over addition. Fewest files, shortest diff.
- **Prefer Nix built-ins.** Use `lib.genAttrs`, `lib.mapAttrs`, `lib.filterAttrs`, `lib.optional`, `lib.mkIf`. No custom iteration helpers.
- **Tests every change.** Run `nix flake check` (or targeted `nix build .#<package>`) after every change. Show evidence.
- **Fix root cause, not symptom.** One guard in the shared function beats a guard in every caller.

## Specs

All planning output goes to `specs/`:

- `specs/product/` — scope, vision, glossary
- `specs/epics/` — structured work items with `verify:` gates
- `specs/release-plan.yaml` — release index
- `specs/tech-architecture/` — architecture, security, test, design docs
- `specs/bugs/registry.yaml` — bug tracker

## Never

- Never edit `nix/repositories.nix` by hand
- Never weaken `--replace-fail` to `--replace`
- Never add a new Python dependency without discussion
- Never pull from the internet at build time
- Never skip preflight on "it worked before"
