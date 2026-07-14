# otter-shell-nix

A workspace-aware Nix flake for packaging Otter Shell from its independent
Forgejo repositories.

This framework is generated from the committed, remote npins sources:

- coordinated release: `0.11.43`
- required Zig: `0.16.0`
- 45 Otter source repositories in the dependency graph
- 33 application packages
- 17 fixed-output external Zig sources
- 2 separately pinned support sources: `parakeet.cpp` and Ghostty

## Design decisions

1. **The flake builds with its own pinned nixpkgs.** The overlay re-exports those
   already-defined packages; it does not silently substitute a consumer's Zig.
2. **Zig 0.16 is mandatory.** There is no fallback to an arbitrary `pkgs.zig`.
3. **Normal patch semantics work.** The custom unpack phase creates the complete
   sibling workspace, then enters the selected component. Nix applies downstream
   `patches` normally; framework substitutions run afterward through `postPatch`.
4. **External Zig dependencies are merged across the full repository dependency
   closure.** The merged directory is linked directly to
   `$ZIG_GLOBAL_CACHE_DIR/p`.
5. **Repository dependencies live in one generated graph.** Package policy and
   runtime/service decisions stay in the smaller hand-maintained
   `nix/package-specs.nix`.
6. **Versions come from npins metadata.** Release pins become normal versions;
   branch pins become `unstable-<revision>`.
7. **Both namespaced and flat overlay access are exported.** Prefer
   `pkgs.otter-shell.otter-bar`; `pkgs.otter-bar` is retained for convenience.

## Building from a clean clone

The committed npins files, generated Zig locks, and Ghostty's revision-matched
upstream Nix lock are the complete source description.
Neither consumers nor CI need a `repos/` directory or a pre-cloned Otter
workspace:

```bash
nix build .#otter-bar
```

Nix fetches the pinned Forgejo and support sources plus their fixed-output
dependencies as normal derivation inputs. Builds remain network-free inside
the Nix sandbox.

Remote-only Nix builds have completed successfully for `otter-shell-core`,
`otter-shell-extras`, `otter-shell-system`, and `otter-shell-all`. Together
these cover all 33 supported x86_64 application packages, including the harder
`otter-assist`, `otter-rec`, `otter-transcribe`, `otter-term`, and greeter
paths. These results prove package compilation and installation, not live
Wayland, PAM, Polkit, DRM/KMS, or GPU behavior. See `VALIDATION.md` for the
current boundary.

## Maintainer bootstrap

The bootstrap shell also evaluates if `npins/` has not been initialized, which
is useful when creating a new fork from scratch:

```bash
nix develop .#bootstrap
./tools/pin-release.sh 0.11.43
./tools/generate-repositories.py
./tools/gen-locks.sh
nix build path:.#otter-bar
```

The `path:.` build form includes newly generated files before they are staged in
Git. Commit `flake.lock`, `npins/default.nix`, `npins/sources.json`, generated
repository metadata, and `locks/*.nix` together. Once committed, consumers use
the normal `.#package` form and run no bootstrap command.

The release script pins the coordinated `v0.11.x` repositories at that tag.
`otter-hypr`, which is outside the coordinated release set in the pinned
zenith metadata, and `otter-examples`, which has its own `0.0.x` version line,
are pinned to exact revisions from `main`. It also pins `parakeet.cpp` and
Ghostty; Ghostty's source carries the exact Zig 0.15 Nix dependency lock used by
its VT library.

For coordinated development heads instead of a release:

```bash
nix develop .#bootstrap
./tools/pin-heads.sh
./tools/generate-repositories.py
./tools/gen-locks.sh
```

## Updating

The normal remote-only refresh is:

```bash
nix develop .#bootstrap
./tools/update.sh
nix flake check
```

`update.sh` updates the requested npins sources, regenerates
`nix/repositories.nix` and `SOURCE-ANALYSIS.json` from those fetched pins,
regenerates the complete recursive Zig lock set, checks source compatibility,
and runs the framework gate. Before changing pins it audits the live Forgejo
organization, and the framework rejects mixed versions in the coordinated
release set. It does not read `repos/`. If Ghostty advances, its upstream VT
recipe and dependency lock advance in the same source pin.

For a new coordinated release:

```bash
./tools/pin-release.sh 0.11.44
./tools/generate-repositories.py
./tools/gen-locks.sh
python3 tools/check-source-compat.py
python3 tools/check-framework.py
nix flake check
```

Selected pin updates still regenerate the graph and complete lock set:

```bash
./tools/update.sh otter_bar otter_ui otter_render
```

Review source revisions, generated graph changes, and lock diffs together.

Local sibling checkouts are optional diagnostics only. To compare the committed
remote-derived metadata with an edited workspace or extracted snapshot:

```bash
./tools/generate-repositories.py --source-root /path/to/otter-workspace
./tools/check-source-compat.py --source-root /path/to/otter-workspace
./tools/generate-zig-locks.py \
  --source-root /path/to/otter-workspace --inventory-only
```

`SOURCE-ANALYSIS.json` records the exact graph used to create the package set.

Compare the generated graph with the Forgejo organization API before a release:

```bash
./tools/audit-upstream.sh
```

This reports newly added or removed repositories, exits non-zero on drift, and
does not silently change the package set.

## Package surface

```nix
pkgs.otter-shell.otter-bar
pkgs.otter-shell.otter-launcher
pkgs.otter-shell.otter-assist
pkgs.otter-shell.otter-assistant
pkgs.otter-shell.fonts
pkgs.otter-shell.core
pkgs.otter-shell.extras
pkgs.otter-shell.system
pkgs.otter-shell.all
```

`core` contains the normal shell and small helpers; `extras` contains tools,
optional widgets, and model-heavy applications; `system` contains the greeter.
Flat aliases such as `pkgs.otter-bar` are also present.

## Patching

Override a package normally:

```nix
pkgs.otter-shell.otter-bar.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ./my-bar.patch ];
})
```

Patches are applied from the component repository root, while its sibling repos
remain at `../otter-*`. Framework-owned FHS/network substitutions run in
`postPatch`, after those patches.

## Local source development

`npins` supports source overrides. For example:

```bash
NPINS_OVERRIDE_otter_bar=$PWD/../otter-bar \
  nix build --impure .#otter-bar
```

Override every locally edited sibling that participates in the package closure.

## Modules

The Home Manager module installs enabled components and creates user services
for daemon-style components. It expects the overlay, or explicit package
options. The NixOS module enables common system prerequisites such as PipeWire,
UPower, Polkit, the privileged `pkexec` wrapper, and the PAM service for
`otter-lock`.

These are two separate switches: `services.otter-shell.enable` configures the
NixOS prerequisites, while `programs.otter-shell.enable` installs and starts the
Home Manager components. A complete integrated NixOS + Home Manager example is
provided in [`examples/consumer-flake.nix`](examples/consumer-flake.nix), with
the corresponding system and user modules beside it. Replace the example flake
URL, username, state versions, and host hardware/boot configuration before use.

The greeter package is exposed, but configuring it as a NixOS display manager is
left separate until its account, PAM, compositor-session, and upgrade semantics
are tested on NixOS.

For DRM/KMS capture, Nix store files cannot be modified with `setcap`. Enable the
NixOS capability wrapper explicitly:

```nix
services.otter-shell.enableRecorderKmsWrapper = true;
```

The module also exports `OTTER_REC_KMS_SERVER` to the graphical login session so
the recorder selects the capability-bearing `/run/wrappers/bin` helper instead
of the unprivileged copy installed with the package.

The recorder's NVIDIA path dynamically opens the host driver's `libcuda.so.1`;
it does not link the CUDA toolkit. To keep the package build free of an unfree
CUDA SDK, the flake supplies only the stable driver-ABI declarations used by
the recorder in `nix/cuda-driver-abi.h`. The successful `otter-rec` build
validates those declarations at compile time. NVIDIA acceleration still
requires a compatible host driver to expose `libcuda.so.1` at runtime, and both
that path and DRM/KMS capture need testing on the target machine.

`otter-assist` is packaged without a GGUF model so the flake does not silently
add a large, separately distributed model to every closure. Enabling its user
service therefore requires an explicit model. The graphical client is a
separate component:

```nix
programs.otter-shell = {
  enable = true;
  components.otter-assist.enable = true;
  components.otter-assistant.enable = true;
  assist.model = "/var/lib/otter-assist/model.gguf";
};
```

Use a Nix store path instead when the model is packaged reproducibly. The
backend and its local-socket client are currently limited to `x86_64-linux`.

## Known hard edges

- `otter-assist` uses the exact llama.cpp `b9789` source expected upstream, but
  intentionally does not bundle a GGUF. Configure `programs.otter-shell.assist.model`
  when enabling its Home Manager service.
- `otter-transcribe` performs an upstream network clone during its normal build.
  This flake pins `parakeet.cpp` separately, injects it, and disables that clone.
- Large embedded models/fonts must be present in the upstream source archive.
  If the Forgejo archive returns Git LFS pointer files, package those assets as
  separate fixed-output sources rather than allowing network access in a build.
- `otter-render` and terminal defaults hardcode FHS font/sound paths upstream.
  The framework patches them to the separately built font package, PulseAudio
  `paplay`, and the freedesktop sound theme in the Nix store. The lock-screen
  default image is patched to the package's own output.
- `otter-term` requires development Ghostty VT APIs newer than the library in
  the pinned nixpkgs. The flake therefore builds `libghostty-vt` from the
  separately pinned Ghostty source using that revision's own Nix recipe and
  Zig 0.15 dependency lock.
- `otter-hypr` follows `main` outside the coordinated release line. The current
  source is adapted to the release theme's `Theme.csd` titlebar namespace, with
  source compatibility checks guarding that boundary during updates.
- `otter-rec` builds without an unfree CUDA toolkit by compiling against the
  committed minimal driver-ABI declarations. Its optional NVIDIA path still
  depends on the host's dynamically loaded driver at runtime.
- Packages use `-Dcpu=baseline` by default rather than inheriting native builder
  CPU features. `otter-vox` remains x86_64-only because upstream itself
  hardcodes AVX/AVX2 compiler flags.
- Commands such as `xdg-open`, `wl-copy`, and `hyprctl` are supplied through
  package-local wrappers where the source uses them. `pkexec` deliberately
  remains a PATH lookup so NixOS resolves the privileged wrapper at
  `/run/wrappers/bin/pkexec`; `services.otter-shell.enablePolkit` enables both
  Polkit and `security.polkit.enablePkexecWrapper`.
- Runtime integration varies by compositor and should be tested component by
  component before enabling the full bundle.

## Validation and maintenance

See `VALIDATION.md` for the checks performed on this generated framework and the
remaining first-build verification steps. `MAINTENANCE.md` contains the release,
new-component, and build-failure workflow intended for long-term stewardship.
The committed GitHub workflow repeats the clean-source compatibility and lock
checks, evaluates an aarch64 representative derivation, builds `otter-bar` and
`otter-term`, and verifies `MANIFEST.sha256` against the complete tracked
release checkout.
