# Maintenance workflow

This repository deliberately separates generated upstream facts from packaging
policy. Keep that boundary intact: regenerate `nix/repositories.nix` and
`SOURCE-ANALYSIS.json`; edit `nix/package-specs.nix` by hand.

The current public surface is derived from 45 pinned Otter sources, 33 package
specifications, 17 fixed-output external Zig sources, and the separately pinned
`parakeet.cpp` and Ghostty support trees. Normal maintenance is remote-only: the
generators resolve repositories through npins and do not require `repos/`.

## Routine pin refresh

```bash
nix develop .#bootstrap
./tools/update.sh
nix flake check path:. --show-trace
```

`update.sh` first audits the live Forgejo organization, then updates all
requested npins pins, regenerates the repository graph and source analysis from
the fetched sources, regenerates every Zig lock closure, checks source
substitutions, and runs `tools/check-framework.py`. The framework rejects a
mixed coordinated release if upstream publishes tags only partially. Pin a
subset by passing npins names, for example `./tools/update.sh otter_bar
otter_ui`; graph and lock generation still cover the complete pinned Otter
source set. Ghostty carries its own matching VT recipe and Zig 0.15 lock, so
updating that pin advances the recipe and lock together.

## Coordinated release update

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

`generate-repositories.py` can inspect each npins source independently. The
release workflow above therefore needs no sibling workspace. A local workspace
can optionally provide a deeper source-compatibility audit of cross-repository
paths and Nix-specific source literals:

```bash
./tools/check-source-compat.py --source-root /path/to/otter-sibling-workspace
./tools/generate-zig-locks.py \
  --source-root /path/to/otter-sibling-workspace --inventory-only
```

Treat `--source-root` as a development and drift-diagnosis option, not as a
source of unpublished inputs. Regenerate committed outputs without that option
before release so they are reproducible from npins alone.

Review and commit these together:

- `flake.lock` when nixpkgs/tooling changed;
- `npins/sources.json` and `npins/default.nix`;
- `locks/*.nix`;
- generated repository metadata;
- source compatibility patches and package policy changes;
- `MANIFEST.sha256`, regenerated last after every other tracked release file is
  final.

## Add a new Otter repository

1. Pin it with the same release/head policy as its upstream peers.
2. Regenerate repository metadata from npins, without relying on a local clone.
3. When it installs a runnable program, add one entry to
   `nix/package-specs.nix`; pure library repositories need no package spec.
4. Add system libraries, native tools, or runtime tools to the maps in
   `nix/packages.nix` only when the generated graph or source audit requires
   them.
5. Add a source-level assertion to `tools/check-source-compat.py` for every
   Nix-specific substitution.
6. Generate locks and build the new package directly before adding it to a
   default tier.

## Diagnose a failed build

- **Missing sibling path:** regenerate `nix/repositories.nix`; do not hand-copy a
  dependency into one package.
- **Zig tries the network:** identify which repository in the transitive closure
  owns the URL dependency, regenerate the full lock set from npins, and confirm
  the generated `<zig-package-hash>.tar.gz` archive appears in the merged cache.
- **`pkg-config` cannot find a library:** add the real nixpkgs package to the
  system-dependency map. Do not set global FHS search paths.
- **Command not found at runtime:** add a narrow `runtimeTools` entry so only the
  affected executables receive a wrapped `PATH`.
- **Hardcoded `/usr` path:** prefer a package output or NixOS wrapper and assert
  the exact upstream literal in `check-source-compat.py`.
- **Recorder asks for CUDA headers:** first determine whether upstream added a
  new dynamically loaded CUDA driver-API declaration. Extend the committed
  `nix/cuda-driver-abi.h` only for that stable ABI surface and keep the source
  compatibility assertions exact. Do not add an unfree CUDA SDK unless the
  recorder actually begins linking against the toolkit.
- **Terminal Ghostty API mismatch:** verify that the Ghostty pin still exports
  the APIs asserted by `tools/check-source-compat.py`. Use the recipe and lock
  from that same Ghostty source revision; do not substitute the older
  `libghostty-vt` from nixpkgs.
- **Patch no longer applies:** inspect the upstream change first. Removing a
  stale workaround is better than weakening `--replace-fail`.

## Release gate

A public release should pass, on both `x86_64-linux` and `aarch64-linux` where
applicable:

```bash
nix develop .#bootstrap --command python3 tools/check-source-compat.py
nix develop .#bootstrap --command python3 tools/generate-zig-locks.py --check
nix develop .#bootstrap --command python3 tools/check-framework.py
nix develop .#bootstrap --command python3 tools/check-manifest.py
nix flake check
nix build .#otter-shell-core
nix build .#otter-shell-extras
nix build .#otter-shell-system
nix build .#otter-shell-all
```

Regenerate `MANIFEST.sha256` only after the release tree is otherwise final:

```bash
python3 tools/check-manifest.py --write
```

`tools/check-manifest.py` excludes the manifest itself, rejects malformed,
duplicate, unsafe, missing, extra, or stale entries, and checks exact tracked
file coverage when run from Git. The committed GitHub workflow runs this from a
clean checkout. It also checks remote source substitutions and committed Zig
lock roots, runs `nix flake check`, evaluates the aarch64 `otter-bar`
derivation, and builds `otter-bar` plus the Ghostty-dependent `otter-term` on
its Linux runner. Keep that representative gate distinct from the broader
per-release build matrix above.

Also test the Home Manager services in a fresh graphical session, Polkit and PAM
flows, notification ownership, clipboard behavior, audio, and recorder KMS
capture. For NVIDIA acceleration, test that the host driver makes
`libcuda.so.1` available to the session; the package deliberately supplies ABI
declarations but no CUDA toolkit or driver. The greeter should remain
package-only until it has a dedicated NixOS VM test.
