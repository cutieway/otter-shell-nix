# Design decisions

This document records the framework choices that should remain stable as the
Otter repositories evolve.

## 1. Zig and nixpkgs ownership

Packages are instantiated with this flake's pinned `nixpkgs`, and require
`zig_0_16` exactly. The overlay re-exports those derivations into a consumer's
package set. It does not rebuild against the consumer's arbitrary Zig version.

This makes a package revision mean the same thing for every consumer. Updating
Zig is a deliberate framework change: update the pinned `nixpkgs`, update the
required Zig attribute, regenerate locks, and test the package set together.

## 2. Patches use standard derivation semantics

The builder has a custom `unpackPhase`, not `dontUnpack = true`. It copies the
transitive sibling workspace, changes into the selected component repository,
sets `sourceRoot`, and then returns to Nix's normal phase sequence. The standard
patch phase therefore applies downstream `patches` from the component root; the
framework's source substitutions are composed into the derivation's `postPatch`
hook and run afterward.

The nixpkgs Zig setup hook is present because `zig_0_16` is a native build input,
but all four `dontUseZig*` switches are set. The framework deliberately owns
configure/build/check/install phase behavior for the multi-repository workspace.

## 3. Zig dependency cache

Every repository in an application's transitive repository dependency closure is
checked for URL dependencies. Its generated fixed-output lock derivation is
combined with the others using `buildEnv`; that merged tree is linked directly
as:

```text
$ZIG_GLOBAL_CACHE_DIR/p -> /nix/store/...-otter-zig-deps
```

There is no extra `p/deps` directory. Zig 0.16 cache entries are archives named
`<zig-package-hash>.tar.gz`. Missing lock files or fixed-output sources produce
an intentional, early failure naming the missing data.

## 4. Versions

`npins/sources.json` is the source of truth. A release pin's `version` becomes
the package version after removing a leading `v`. A branch pin becomes
`unstable-<8-character revision>`. The original snapshot version remains in the
generated repository metadata for auditing, not as the live derivation version.

## 5. Workspace dependency ownership

`nix/repositories.nix` is a generated central graph containing local sibling
dependencies, minimum Zig versions, external-dependency presence, and linked
system libraries. `nix/package-specs.nix` is intentionally hand-maintained and
contains only packaging policy: executable, tier, service behavior, exceptional
system dependencies, extra sources, and source patches.

This separation avoids repeating dependency lists in 33 package files while
keeping generated facts separate from human policy.

## 6. Remote source model

The 45 Otter repositories are normal npins sources. Repository metadata and Zig
locks are regenerated from `npins get-path`, so a clean clone, CI runner, or
consumer never needs the development `repos/` directory. The 17 external Zig
sources are fixed-output derivations and are normalized into Zig 0.16 cache
archives before sandboxed compilation begins.

Two non-Otter support trees are also normal remote npins sources.
`parakeet.cpp` is injected into `otter-transcribe`; Ghostty provides the
development VT library needed by `otter-term`. Ghostty is built with the Nix
recipe and Zig 0.15 dependency lock committed in the exact pinned Ghostty
revision, rather than being forced through the Otter Zig 0.16 lock generator.

`tools/update.sh` is the canonical refresh path: it updates requested npins
pins after auditing the live Forgejo repository set, regenerates the central
graph and `SOURCE-ANALYSIS.json`, regenerates all recursive Zig locks, checks
compatibility substitutions against the remote sources, and runs the framework
check. The framework also requires every coordinated release pin to carry one
common tag version. The generators accept `--source-root` only for optional
local development and diagnostic comparisons; published outputs must be
reproducible from the pins alone.

## 7. Bootstrap order

The committed npins and lock files are sufficient for an ordinary build:

```bash
nix build .#otter-bar
```

Flake evaluation remains lazy with respect to `npins`: before initialization it
returns empty source and pin sets, allowing a maintainer to create a new fork
from scratch. That exceptional bootstrap sequence is:

```bash
nix develop .#bootstrap
./tools/pin-release.sh 0.11.43
./tools/generate-repositories.py
./tools/gen-locks.sh
nix build path:.#otter-bar
```

`pin-release.sh` runs `npins init --bare` itself when necessary. No command
requires an already initialized `npins/` before entering the bootstrap shell.

No bootstrap step is part of the consumer workflow.

## 8. Overlay shape

The preferred API is namespaced:

```nix
pkgs.otter-shell.otter-bar
pkgs.otter-shell.core
```

Flat aliases such as `pkgs.otter-bar` are exported as a convenience and for
simple package overrides. Both aliases refer to derivations built from this
flake's pinned `nixpkgs`.

## 9. Release integrity and remote gate

`MANIFEST.sha256` describes the tracked public release tree without recursively
hashing itself. `tools/check-manifest.py` verifies checksum syntax, path safety,
uniqueness, file presence, content, and—when Git metadata is available—exact
coverage of every tracked path. It is regenerated only after the rest of a
release is final.

The committed GitHub workflow is the clean-source enforcement boundary. It
uses read-only repository permissions and commit-pinned third-party Actions,
checks source substitutions against npins, checks committed Zig lock roots,
runs the flake checks, evaluates a representative aarch64 derivation, builds
`otter-bar` plus the Ghostty-dependent `otter-term`, and validates the manifest.
This remote gate supplements rather than replaces the wider package matrix and
live NixOS/Home Manager testing.

## Source-specific exceptions

- `otter-assist` injects the exact llama.cpp `b9789` archive because Forgejo
  release archives do not include submodule contents. Its large GGUF model is
  not part of the package; the Home Manager module requires an explicit model
  path before enabling the daemon.
- `otter-transcribe` normally clones `parakeet.cpp` during its build. The flake
  pins that repository with submodules, injects it into `vendor/parakeet.cpp`,
  and patches the network commands out.
- `otter-term` uses development Ghostty VT APIs. The flake pins Ghostty and
  calls that revision's `nix/libghostty-vt.nix`, which consumes its matching
  `build.zig.zon.nix` cache description.
- `otter-hypr` follows `main` outside the coordinated release set. Its current
  titlebar renderer is patched from the former `Theme.decorations` color
  namespace to the `Theme.csd` namespace provided by the pinned release theme.
- `otter-vox` currently hardcodes x86 SIMD flags including AVX2, so its package
  metadata restricts it to `x86_64-linux` until upstream makes those flags
  target-aware.
- Executables with ordinary command-line dependencies are wrapped with a local
  `PATH`. Absolute non-privileged commands in settings/recorder sources are
  patched to Nix-store paths. `pkexec` is intentionally not patched or prefixed:
  NixOS must resolve `/run/wrappers/bin/pkexec`, and the NixOS module enables the
  dedicated Polkit `pkexec` wrapper option.
- `otter-rec-kms-server` cannot receive capabilities by mutating its Nix-store
  file. The NixOS module exposes an opt-in `security.wrappers` capability
  wrapper instead.
- `otter-rec` dynamically opens the host NVIDIA driver's `libcuda.so.1` rather
  than linking the CUDA toolkit. The flake injects the narrow, committed
  `nix/cuda-driver-abi.h` declarations needed by that loader and FFmpeg's CUDA
  context types. This keeps the package build independent of an unfree CUDA SDK
  while leaving driver installation and GPU compatibility as host runtime
  responsibilities.
- The greeter is packaged but not automatically configured as a display manager.
  PAM, users, compositor launch, session lifecycle, and upgrades should be
  tested before exposing that as a stable NixOS module option.
- Fonts are packaged from the pinned `otter-render` source. Shared font paths,
  the terminal bell command/sound, and the lock-screen default image are patched
  to immutable package paths rather than upstream FHS paths.
- Large model assets must come from fixed, content-addressed sources. A
  sandboxed package must never download them during `buildPhase` or runtime
  installation.

## Cross-platform bundles

Individual package attributes remain visible on both supported flake systems,
but aggregate bundles filter with `lib.meta.availableOn`. This keeps the current
x86_64-only `otter-vox` out of aarch64 bundles instead of making the whole
bundle unbuildable.
