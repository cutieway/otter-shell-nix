{ pkgs, lib }:
{
  pname,
  version,
  repoDir,
  workspace,
  externalDeps,
  missingPins ? [ ],
  missingLocks ? [ ],
  missingSystemDeps ? [ ],
  extraSources ? [ ],
  zig,
  optimize ? "ReleaseFast",
  zigBuildFlags ? [ ],
  nativeBuildInputs ? [ ],
  buildInputs ? [ ],
  runtimeInputs ? [ ],
  patches ? [ ],
  postUnpack ? "",
  postPatch ? "",
  preBuild ? "",
  postInstall ? "",
  doCheck ? false,
  meta ? { },
  passthru ? { }
}:
let
  errors =
    lib.optional (missingPins != [ ]) "missing pins: ${lib.concatStringsSep ", " missingPins}"
    ++ lib.optional (missingLocks != [ ]) "missing Zig dependency locks: ${lib.concatStringsSep ", " missingLocks}"
    ++ lib.optional (missingSystemDeps != [ ]) "missing nixpkgs packages: ${lib.concatStringsSep ", " missingSystemDeps}";
  failMessage = lib.concatStringsSep "; " errors;
  copyExtra = lib.concatMapStringsSep "\n" (entry: ''
    mkdir -p "$(dirname ${lib.escapeShellArg entry.target})"
    cp -RL --no-preserve=mode,ownership \
      ${lib.escapeShellArg "${workspace}/__extra-${entry.pin}/."} \
      ${lib.escapeShellArg entry.target}
  '') extraSources;

  # Convert git+https:// URLs from build.zig.zon to local path references
  # so sibling repos in the workspace are resolved without network access.
  # Release archives use both single-line and multi-line dependency records,
  # so operate on each complete file rather than assuming a line layout.
  patchZonDeps = ''
    echo "otter-shell-nix: patching build.zig.zon files to use workspace paths..."
    find .. -mindepth 2 -maxdepth 2 -name build.zig.zon -print0 |
    while IFS= read -r -d "" zon; do
      sed -z -i -E \
        's@\.url[[:space:]]*=[[:space:]]*"git\+https://git\.pika-os\.com/otter-shell/([a-zA-Z0-9_-]+)\.git[^"]*"[[:space:]]*,[[:space:]]*\.hash[[:space:]]*=[[:space:]]*"[^"]*"@.path = "../\1"@g' \
        "$zon"

      if grep -q 'git+https://git\.pika-os\.com/otter-shell/' "$zon"; then
        echo "otter-shell-nix: failed to localize an Otter dependency in $zon" >&2
        exit 1
      fi
    done
  '';
  setupCache = ''
    export HOME="$TMPDIR/home"
    export ZIG_GLOBAL_CACHE_DIR="$TMPDIR/zig-global-cache"
    export ZIG_LOCAL_CACHE_DIR="$TMPDIR/zig-local-cache"
    mkdir -p "$HOME" "$ZIG_LOCAL_CACHE_DIR" "$(dirname "$ZIG_GLOBAL_CACHE_DIR/p")"
    rm -rf "$ZIG_GLOBAL_CACHE_DIR/p"
    ln -s ${externalDeps} "$ZIG_GLOBAL_CACHE_DIR/p"
  '';
  # Directory carrying the toolchain's own runtime libraries (libstdc++ for
  # C++ shims). The compiler driver finds these internally, so they never
  # appear in NIX_LDFLAGS; seed them for the preFixup library lookup below.
  toolchainLibDir = "${lib.getLib pkgs.stdenv.cc.cc}/lib";
in
pkgs.stdenv.mkDerivation {
  inherit
    pname
    version
    patches
    doCheck
    postUnpack
    postPatch
    preBuild
    postInstall
    ;

  src = workspace;

  nativeBuildInputs = [ zig pkgs.pkg-config pkgs.patchelf ]
    ++ lib.optional (runtimeInputs != [ ]) pkgs.makeWrapper
    ++ nativeBuildInputs;
  inherit buildInputs;

  strictDeps = true;

  # The nixpkgs Zig package ships a setup hook that can synthesize phases.
  # This builder owns those phases because it must assemble a multi-repository
  # workspace and a merged dependency cache first.
  dontUseZigConfigure = true;
  dontUseZigBuild = true;
  dontUseZigCheck = true;
  dontUseZigInstall = true;
  dontConfigure = true;

  unpackPhase = ''
    runHook preUnpack
    mkdir -p workspace
    # Some upstreams vendor sysfs fixture trees containing cyclic symlinks
    # (e.g. otter-bench tests/fixtures/sysfs), which no copy can represent.
    # GNU cp copies everything else and skips only those links; the fixtures
    # back `zig build test`, which never runs in a package build, so warn and
    # continue instead of failing the whole workspace copy. Anything the
    # build itself needs still fails loudly below.
    cp -RL --no-preserve=mode,ownership "$src/." workspace/ || \
      echo "otter-shell-nix: workspace copy skipped unreadable links (see cp errors above)" >&2
    chmod -R u+w workspace
    cd "workspace/${repoDir}"
    sourceRoot="$PWD"
    ${copyExtra}
    ${patchZonDeps}
    runHook postUnpack
  '';

  buildPhase = ''
    runHook preBuild
    ${lib.optionalString (errors != [ ]) ''
      echo "otter-shell-nix: cannot build ${pname}: ${failMessage}" >&2
      exit 1
    ''}
    ${setupCache}
    zig build -j"''${NIX_BUILD_CORES:-1}" \
      -Doptimize=${lib.escapeShellArg optimize} \
      ${lib.escapeShellArgs zigBuildFlags}
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    ${setupCache}
    zig build -j"''${NIX_BUILD_CORES:-1}" \
      -Doptimize=${lib.escapeShellArg optimize} \
      ${lib.escapeShellArgs zigBuildFlags} \
      --prefix "$out" \
      install
    runHook postInstall
  '';

  checkPhase = ''
    runHook preCheck
    ${setupCache}
    zig build -j"''${NIX_BUILD_CORES:-1}" \
      -Doptimize=${lib.escapeShellArg optimize} \
      ${lib.escapeShellArgs zigBuildFlags} \
      test
    runHook postCheck
  '';

  # Upstream core libraries (otter-utils, otter-ui, ...) now link as shared
  # objects. Zig emits those into its local cache and records the cache
  # directory in the binary RPATH. The cache lives under /build, which must
  # not leak into the closure, and the libraries must ship in $out/lib or
  # the binaries cannot start. Harvest every DT_NEEDED entry that is not
  # already satisfied from the store, then drop the /build RPATH entries.
  # System libraries the linker resolved (e.g. libstdc++ for C++ shims)
  # gain an RPATH entry instead of a copy. This runs in preFixup: fixupPhase
  # rejects /build references, so the rewrite must land before its checks.
  preFixup = ''
    cacheDir="''${ZIG_LOCAL_CACHE_DIR:-$TMPDIR/zig-local-cache}"
    # Library directories the linker itself searched, in order: the
    # toolchain runtimes first, then every -L directory from the build.
    # NOTE: command substitution strips trailing newlines, so join lines
    # with a literal newline instead of $(printf '%s\n' ...).
    link_dirs="${toolchainLibDir}"
    for flag in ''${NIX_LDFLAGS:-}; do
      case "$flag" in
        -L*) link_dirs="$link_dirs
''${flag#-L}" ;;
      esac
    done
    if [ -d "$out/bin" ] && [ -d "$cacheDir" ]; then
      harvested=0
      sysrpath=0
      sysrpath_dirs=""
      while IFS= read -r -d "" bin; do
        if ! old_rpath="$(patchelf --print-rpath "$bin" 2>/dev/null)"; then
          continue
        fi
        store_dirs="$(printf '%s' "$old_rpath" | tr ':' '\n' | grep -v '^/build' || true)"
        # The Nix glibc loader also resolves libraries relative to itself
        # (e.g. libc.so.6 lives next to ld-linux). Mirror that lookup so
        # loader-resolved libraries are not mistaken for missing ones.
        interp="$(patchelf --print-interpreter "$bin" 2>/dev/null || true)"
        if [ -n "$interp" ]; then
          store_dirs="$store_dirs""$(printf '\n%s/../lib' "$(dirname "$interp")")"
        fi
        while IFS= read -r needed; do
          [ -n "$needed" ] || continue
          satisfied=0
          while IFS= read -r dir; do
            if [ -n "$dir" ] && [ -e "$dir/$needed" ]; then satisfied=1; break; fi
          done <<< "$store_dirs"
          [ "$satisfied" = 1 ] && continue
          [ -e "$out/lib/$needed" ] && continue
          # System library from the link closure: reference it in place.
          sysdir=""
          while IFS= read -r dir; do
            if [ -n "$dir" ] && [ -e "$dir/$needed" ]; then sysdir="$dir"; break; fi
          done <<< "$link_dirs"
          if [ -n "$sysdir" ]; then
            case ":$sysrpath_dirs:" in
              *":$sysdir:"*) ;;
              *) sysrpath_dirs="$sysrpath_dirs:$sysdir"; sysrpath=1 ;;
            esac
            continue
          fi
          hit="$(find "$cacheDir" -name "$needed" 2>/dev/null | sort | head -n 1 || true)"
          if [ -z "$hit" ]; then
            echo "otter-shell-nix: cannot satisfy $bin needs $needed" >&2
            exit 1
          fi
          mkdir -p "$out/lib"
          cp -L "$hit" "$out/lib/$needed"
          chmod 755 "$out/lib/$needed"
          harvested=1
        done < <(patchelf --print-needed "$bin" 2>/dev/null || true)
      done < <(find "$out/bin" -maxdepth 1 -type f -perm -0100 -print0 2>/dev/null || true)
      if [ "$harvested" = 1 ] || [ "$sysrpath" = 1 ]; then
        while IFS= read -r -d "" elf; do
          if ! old_rpath="$(patchelf --print-rpath "$elf" 2>/dev/null)"; then
            continue
          fi
          new_rpath="$(printf '%s' "$old_rpath" | tr ':' '\n' | { grep -v '^/build' || true; } | tr '\n' ':' | sed 's/:$//')"
          combined="$new_rpath$sysrpath_dirs"
          # Never emit a leading empty entry: it means the current directory.
          combined="''${combined#:}"
          case ":$combined:" in
            *":$out/lib:"*) ;;
            *) if [ "$harvested" = 1 ]; then combined="$combined:$out/lib"; fi ;;
          esac
          new_rpath="$combined"
          if [ "$old_rpath" != "$new_rpath" ]; then
            patchelf --set-rpath "$new_rpath" "$elf"
          fi
        done < <(find "$out/bin" "$out/lib" -maxdepth 1 -type f -perm -0100 -print0 2>/dev/null || true)
      fi
    fi
  '';

  postFixup = lib.optionalString (runtimeInputs != [ ]) ''
    while IFS= read -r -d "" program; do
      wrapProgram "$program" \
        --prefix PATH : ${lib.escapeShellArg (lib.makeBinPath runtimeInputs)}
    done < <(find "$out/bin" -maxdepth 1 -type f -perm -0100 -print0 2>/dev/null || true)
  '';

  # GNU strip corrupts binaries emitted by Zig's LLD 21 backend: it relocates
  # .dynsym to end-of-file without updating its address, so the loader cannot
  # resolve any dynamic symbol and _start jumps to NULL (SIGSEGV before main).
  # Only some layouts trip it, but any package can grow into the bad shape, so
  # stripping stays off for every Zig package. Zig already compresses debug
  # sections; the retained symbols also keep crash reports actionable.
  dontStrip = true;
  inherit meta passthru;
}
