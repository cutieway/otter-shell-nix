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

  nativeBuildInputs = [ zig pkgs.pkg-config ]
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
    cp -RL --no-preserve=mode,ownership "$src/." workspace/
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

  postFixup = lib.optionalString (runtimeInputs != [ ]) ''
    while IFS= read -r -d "" program; do
      wrapProgram "$program" \
        --prefix PATH : ${lib.escapeShellArg (lib.makeBinPath runtimeInputs)}
    done < <(find "$out/bin" -maxdepth 1 -type f -perm -0100 -print0 2>/dev/null || true)
  '';

  inherit meta passthru;
}
