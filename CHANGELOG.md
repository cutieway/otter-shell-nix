# Changelog

All notable changes to this packaging framework are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/)
with versions tracking the upstream Otter Shell coordinated release line.

## [Unreleased]

### Added
- Initial repository audit and documentation improvements.
- `.editorconfig` for cross-editor consistency.
- `CLAUDE.md` with AI assistant guidance.
- `CONTRIBUTING.md` with contribution workflow.

### Changed
- NixOS module options now include `description` fields for each option.

### Fixed
- `nativeToolMap` and `runtimeToolMap` lookups in `nix/packages.nix` now
  explicitly return `null` for unrecognized tool names (was silently filtering
  unknowns from build inputs with no error).
- `generate-zig-locks.py` now catches `KeyError` in its top-level exception
  handler alongside `OSError`, `RuntimeError`, and `ValueError`.
- `strip_zig_comments` in `generate-repositories.py` now uses a depth counter
  for block-comment handling, matching the sibling implementation in
  `generate-zig-locks.py`.
- Removed redundant `lib.unique` calls on already-unique lists in
  `nix/packages.nix` and `nix/lib/graph.nix`.

## [0.11.43] — 2026-07-24

### Added
- Initial Otter Shell Nix packaging framework.
- 33 application packages from 45 Otter Shell repositories.
- NixOS module with PipeWire, UPower, Polkit, PAM, and DRM/KMS capability
  wrapper support.
- Home Manager module with per-component enablement, user services for
  daemon-style components, and Sway integration.
- Generated dependency graph (`nix/repositories.nix`) via
  `tools/generate-repositories.py`.
- Recursive Zig lock generation (`tools/generate-zig-locks.py`,
  `tools/gen-locks.sh`) producing lock files in `locks/*.nix`.
- npins-based pinning with SRI hashes for all sources.
- Ghostty VT library built from a separately pinned Ghostty source with
  Zig 0.15 isolation.
- Framework validation (`tools/check-framework.py`) with 30+ structural
  checks: graph acyclicity, lock completeness, pin provenance, version
  consistency, architectural invariants, module correctness.
- Source compatibility checks (`tools/check-source-compat.py`) guarding
  against upstream refactoring drift.
- Release manifest integrity (`tools/check-manifest.py`) with SHA256
  checksums for every tracked file.
- Upstream audit tool (`tools/audit-upstream.sh`) comparing generated
  repository metadata against the Forgejo organization API.
- Design documentation (`DESIGN.md`) with 9 design decisions and rationale.
- Maintenance documentation (`MAINTENANCE.md`) with coordinated release,
  pin refresh, and build diagnosis workflows.
- Validation scope documentation (`VALIDATION.md`) honestly describing
  tested and untested behaviors.
- CI workflow (`.github/workflows/check.yml`) with source validation,
  flake check, aarch64 evaluation, representative builds, and manifest
  verification.
- Examples (`examples/consumer-flake.nix`, `examples/configuration.nix`,
  `examples/home.nix`) demonstrating NixOS + Home Manager integration.

[Unreleased]: https://git.pika-os.com/otter-shell/otter-shell-nix
[0.11.43]: https://git.pika-os.com/otter-shell/otter-shell-nix/src/tag/v0.11.43
