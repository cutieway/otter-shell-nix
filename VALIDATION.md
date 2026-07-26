# Validation status

This repository is generated from remote pinned release sources. The current
graph contains 45 Otter source repositories, 33 runnable application package
specifications, and 17 fixed-output external Zig sources. The coordinated
projects report version `0.11.43` and minimum Zig `0.16.0`.

## Completed locally

The following remote-only structural checks pass in the generation environment:

```text
python3 tools/pipeline.py generate --check
python3 tools/pipeline.py lock --check
python3 tools/pipeline.py check compat
python3 tools/pipeline.py check framework
python3 -m py_compile tools/pipeline.py
```

These commands resolve the Otter repositories through npins. No `repos/`
directory is present or required in a clean clone. The lock-completeness gate
confirms that all per-repository closures resolve through the 17 entries in
`locks/sources.nix`.

All Nix files also parse with `nix-instantiate --parse`. Remote Nix builds now
complete successfully for the full x86_64 package surface:

- `otter-shell-core`, the Home Manager default package set;
- `otter-shell-extras`, including tools and optional/model-heavy components;
- `otter-shell-system`, containing the greeter; and
- `otter-shell-all`, whose final aggregate contains every one of the 33
  supported x86_64 application packages.

The edge-case builds covered by those aggregates include:

- `otter-bar`, the representative shell package;
- `otter-lock`, including the packaged immutable default lock image;
- `otter-rec`, including the committed CUDA driver-ABI shim;
- `otter-transcribe`, including the pinned parakeet.cpp and ggml patch series;
  and
- `otter-term`, using the pinned Ghostty source's revision-matched VT recipe.

The `otter-bar` result validates remote source resolution, workspace assembly,
sibling Forgejo URL rewriting, direct Zig 0.16 archive-cache placement,
compilation, and installation. The recorder result also validates that its
dynamic CUDA-driver bridge compiles without adding an unfree CUDA toolkit or
SDK to the build. These are package-build results only; no graphical, PAM,
Polkit, DRM/KMS, or GPU runtime success is implied.

The static checks cover:

- the full repository dependency graph and absence of cycles;
- package-spec/repository consistency;
- direct Zig 0.16 archive-cache placement at `$ZIG_GLOBAL_CACHE_DIR/p`;
- normal Nix patch semantics and framework substitutions in `postPatch`;
- exact Zig selection without an arbitrary fallback;
- explicit disabling of nixpkgs Zig hook phase synthesis;
- the NixOS Polkit `pkexec` security wrapper;
- source literals used by the transcribe, font, sound, lock, settings, and
  recorder adaptations;
- the recorder's committed minimal CUDA driver-ABI declarations, without an
  unfree CUDA SDK build input;
- the current x86_64 restriction for `otter-vox`.

## Optional local diagnostics

An edited sibling workspace can be checked without making it a release input:

```bash
python3 tools/pipeline.py generate \
  --source-root /path/to/otter-workspace --check
python3 tools/pipeline.py check compat \
  --source-root /path/to/otter-workspace
python3 tools/pipeline.py lock \
  --source-root /path/to/otter-workspace --inventory-only
```

These checks are useful when developing coordinated upstream changes. Public
generation and builds continue to use the committed npins sources.

## Current release validation

The fixed-output lock inventory is complete. The core, extras, system, and all
aggregates have all completed from remote-only sources; the final all-package
join created 125 links. The terminal build additionally proves that Ghostty's
pinned development VT API and its upstream dependency lock match the Otter
source. The out-of-release `otter-hypr` main pin also builds after its guarded
`Theme.csd` compatibility adaptation.

A selected-pin `./tools/pipeline.py update ghostty` run also completed in the clean
checkout: the live 45-repository Forgejo set matched, npins refreshed the
remote pin, all seven Otter lock closures were regenerated with 17 unique
sources, and the coordinated-release, source-compatibility, and framework gates
passed without a local workspace.

The committed clean-checkout gate is:

```bash
nix develop .#bootstrap --command python3 tools/pipeline.py check compat
nix develop .#bootstrap --command python3 tools/pipeline.py lock --check
nix flake check --show-trace
nix eval .#packages.aarch64-linux.otter-bar.drvPath --raw
nix build .#otter-bar .#otter-term --show-trace
nix develop .#bootstrap --command python3 tools/pipeline.py check manifest
```

The GitHub workflow runs those checks from tracked remote content, evaluates
`packages.aarch64-linux.otter-bar.drvPath`, and pins third-party Actions to
immutable commits under read-only repository permissions. The manifest checker
requires every tracked release path except `MANIFEST.sha256` itself to appear
exactly once with its current checksum. This prevents an unlisted or stale file
from passing the public clean-checkout gate.

The NixOS and Home Manager modules still require runtime testing in a real
graphical session.

The aarch64 `otter-shell-core` and `otter-term` derivations evaluate
successfully. Native aarch64 compilation remains part of the release matrix,
not a result claimed from this x86_64 host.

## Repeatable release and real NixOS validation

Repeat the release build set from a clean clone:

```bash
nix flake check path:. --show-trace

nix build --show-trace \
  path:.#otter-shell-core \
  path:.#otter-shell-extras \
  path:.#otter-shell-system \
  path:.#otter-shell-all
```

Then test the less conventional packages separately:

```bash
nix build --show-trace path:.#otter-rec
nix build --show-trace path:.#otter-vox   # x86_64-linux only
nix build --show-trace path:.#otter-transcribe
```

For runtime integration, begin with a dedicated Home Manager generation and
enable one daemon at a time. Test notification ownership, bar layer-shell
behavior, Polkit authentication, lock PAM, audio, and recorder KMS capture
before switching to the aggregate bundle. On NVIDIA systems, additionally
verify that the configured host driver exposes `libcuda.so.1` to the graphical
session and exercise the recorder's accelerated path. A successful package
build does not validate any of these authentication or graphics boundaries.
