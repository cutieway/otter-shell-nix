# Contributing to otter-shell-nix

## Overview

This repository packages Otter Shell components for Nix. The framework is
organized around a clear boundary: **generated** dependency metadata in
`nix/repositories.nix` vs. **hand-maintained** packaging policy in
`nix/package-specs.nix`. Changes to generated files go through their
corresponding tool in `tools/`; changes to packaging policy are hand-written.

## PR workflow

1. **Branch from `main`.** Use a descriptive branch name:
   - `fix/` — bug fixes
   - `feat/` — new packages, module options, or features
   - `doc/` — documentation-only changes
   - `refactor/` — structural changes with no behavior change
   - `chore/` — maintenance, tooling, CI

2. **Run checks before opening a PR:**

   ```bash
   nix develop .#bootstrap
   python3 tools/pipeline.py check all
   nix flake check
   ```

3. **Keep changes focused.** A single PR should address one logical change.
   Refactoring and feature additions belong in separate PRs.

4. **Update docs.** If you add a module option, new package, or change the
   build pipeline, update the relevant documentation (`README.md`,
   `DESIGN.md`, or module option descriptions).

5. **Run `nixfmt`** on any modified `.nix` files before committing:

   ```bash
   nix fmt
   ```

## Commit conventions

- Use conventional commits: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`
- Reference related issues or design decisions when relevant
- Keep commit messages under 72 characters in the subject line
- The body should explain *what* changed and *why*
- Commit generated files (`nix/repositories.nix`, `locks/*.nix`) *together*
  with the tool invocation that produced them, so the diff tells a complete
  story

Example:

```
fix: reject unknown tool names at build time

nativeToolMap.${tool} and runtimeToolMap.${tool} were silently returning
null for unrecognized tool names, which Nix filters from build inputs
without error. This adds explicit `or null` markers and a build-time
assertion so typos or missing entries fail early.
```

## Code style

### Nix

- Format with `nixfmt` before committing
- Use `let-in` over `rec` for attribute sets that need self-reference
- Prefer `builtins.*` for core operations; `lib.*` for everything else
- Use `lib.types.*` for module option types; add `description` to every
  option
- Assertions should produce actionable error messages:

  ```nix
  assert lib.assertMsg (condition) "module: expected X but got Y";
  ```

### Python

- Use `pathlib.Path` for filesystem operations
- Prefer `subprocess.run` with command lists over shell strings
- Main entry points should have `if __name__ == "__main__":`
- Catch specific exceptions, not bare `except:`

### Shell

- `set -euo pipefail` in every script
- Quote all variable expansions
- Use `mktemp` for temporary files, with `trap` cleanup

## Review expectations

- Generated file diffs are reviewed for correctness of the *generation
  logic*, not the generated output itself
- Module option changes must include `description` fields and, where
  appropriate, assertions
- New packages need a spec entry in `nix/package-specs.nix` and may need
  source fixups in `nix/packages.nix`
- Build failures should be diagnosed using `MAINTENANCE.md`'s failure mode
  guide before requesting review
