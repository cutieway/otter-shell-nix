{
  pkgs,
  root,
  sources,
  pins
}:
let
  lib = pkgs.lib;
  repositories = import ./repositories.nix;
  specs = import ./package-specs.nix;
  graph = import ./lib/graph.nix { inherit lib repositories; };
  sourceInfo = import ./lib/source-info.nix { inherit lib pins; };
  mkWorkspace = import ./lib/mk-workspace.nix { inherit pkgs lib; };
  mkZigPackage = import ./lib/mk-zig-package.nix { inherit pkgs lib; };

  zig =
    if builtins.hasAttr "zig_0_16" pkgs then pkgs.zig_0_16 else
      throw "otter-shell-nix: pinned nixpkgs does not provide zig_0_16; update the flake's nixpkgs input";

  renderSource =
    if builtins.hasAttr "otter_render" sources then sources.otter_render else
      pkgs.runCommand "missing-otter-render-source" { } ''
        mkdir -p "$out"
        printf '%s\n' "missing npins source: otter_render" > "$out/MISSING_SOURCE"
      '';

  renderInfo = sourceInfo "otter-render";
  otterFonts = pkgs.stdenvNoCC.mkDerivation {
    pname = "otter-shell-fonts";
    version = renderInfo.version;
    src = renderSource;
    dontBuild = true;
    installPhase = ''
      runHook preInstall
      if [[ ! -d fonts ]]; then
        echo "otter-shell-nix: otter-render source does not contain fonts/" >&2
        exit 1
      fi
      mkdir -p "$out/share/fonts/truetype/otter-shell"
      copied=0
      while IFS= read -r -d "" font; do
        # Catch stripped placeholders and Git LFS pointer files before they turn
        # into a package that only fails later at runtime.
        magic="$(od -An -tx1 -N4 "$font" | tr -d ' \n')"
        case "$magic" in
          00010000|4f54544f|74727565|74797031) ;;
          *)
            echo "otter-shell-nix: invalid or placeholder font: $font" >&2
            exit 1
            ;;
        esac
        cp -v "$font" "$out/share/fonts/truetype/otter-shell/"
        copied=$((copied + 1))
      done < <(find fonts -maxdepth 1 -type f \
        \( -iname '*.ttf' -o -iname '*.otf' \) -print0)
      if [[ $copied -eq 0 ]]; then
        echo "otter-shell-nix: otter-render contains no usable TTF/OTF fonts" >&2
        exit 1
      fi
      runHook postInstall
    '';
    meta = {
      description = "Fonts used by Otter Shell";
      homepage = "https://git.pika-os.com/otter-shell/otter-render";
      platforms = lib.platforms.linux;
    };
    passthru = {
      sourceRevision = renderInfo.revision;
      sourceRelease = renderInfo.release;
    };
  };

  soundTheme = pkgs."sound-theme-freedesktop";
  termBellPlayer = "${pkgs.pulseaudio}/bin/paplay";
  termBellSound = "${soundTheme}/share/sounds/freedesktop/stereo/bell.oga";

  ghosttySource =
    if builtins.hasAttr "ghostty" sources then sources.ghostty else
      pkgs.runCommand "missing-ghostty-source" { } ''
        mkdir -p "$out"
        printf '%s\n' "missing npins source: ghostty" > "$out/MISSING_SOURCE"
      '';
  ghosttyVt =
    if builtins.hasAttr "ghostty" sources && builtins.hasAttr "ghostty" pins then
      # Otter consumes Ghostty's development VT API. Use the recipe and Zig
      # dependency lock shipped by that exact source revision so both advance
      # atomically when npins updates the pin.
      pkgs.callPackage (ghosttySource.outPath + "/nix/libghostty-vt.nix") {
        revision = pins.ghostty.revision;
        optimize = "ReleaseFast";
      }
    else
      null;

  maps = import ./lib/dependency-maps.nix { inherit pkgs lib ghosttyVt; };
  systemDependencyMap = maps.systemDependencyMap;
  namedDependencyMap = maps.namedDependencyMap;
  nativeToolMap = maps.nativeToolMap;
  runtimeToolMap = maps.runtimeToolMap;

  packageSourceFixups = import ./lib/package-source-fixups.nix { inherit pkgs lib; };

  lockPathFor = repo: root + "/locks/${repo}.nix";

  mkExternalDeps = closure:
    let
      lockRepos = builtins.filter (repo: repositories.${repo}.hasRemoteDeps) closure;
      present = builtins.filter (repo: builtins.pathExists (lockPathFor repo)) lockRepos;
      paths = map (repo: pkgs.callPackage (lockPathFor repo) { inherit zig; }) present;
    in
    {
      missing = builtins.filter (repo: !builtins.pathExists (lockPathFor repo)) lockRepos;
      env = pkgs.buildEnv {
        name = "otter-zig-deps";
        inherit paths;
        pathsToLink = [ "/" ];
        ignoreCollisions = true;
      };
    };

  resolveSystemDeps = closure: extra:
    let
      libraryNames = lib.unique (lib.concatMap (repo: repositories.${repo}.systemLibraries) closure);
      mapped = map (name: systemDependencyMap.${name} or null) libraryNames;
      mappedPackages = map (item: if item == null then null else item.package) mapped;
      extraPackages = map (name: namedDependencyMap.${name} or null) extra;
      missingFromLibraries = map (item: item.name) (builtins.filter (item: item != null && item.package == null) mapped);
      missingFromExtra = builtins.filter (name: (namedDependencyMap.${name} or null) == null) extra;
    in
    {
      packages = lib.unique (builtins.filter (x: x != null) (mappedPackages ++ extraPackages));
      missing = lib.unique (missingFromLibraries ++ missingFromExtra);
    };

  sourceMissing = repo: !builtins.hasAttr repositories.${repo}.pin sources;

  mkOne = name: spec:
    let
      closure = graph.closureFor name;
      external = mkExternalDeps closure;
      sys = resolveSystemDeps closure (spec.extraSystemDeps or [ ]);
      extraSources = spec.extraSources or [ ];
      missingExtraPins = map (entry: entry.pin) (builtins.filter (entry: !builtins.hasAttr entry.pin sources) extraSources);
      workspace = mkWorkspace {
        inherit repositories sources closure extraSources;
      };
      info = sourceInfo name;
      fontDir = "${otterFonts}/share/fonts/truetype/otter-shell/";
      nativeToolsResolved = builtins.map (tool: nativeToolMap.${tool} or null) (spec.nativeTools or [ ]);
      runtimeToolsResolved = builtins.map (tool: runtimeToolMap.${tool} or null) (spec.runtimeTools or [ ]);
      unknownNativeTools = builtins.filter (tool: !builtins.hasAttr tool nativeToolMap) (spec.nativeTools or [ ]);
      unknownRuntimeTools = builtins.filter (tool: !builtins.hasAttr tool runtimeToolMap) (spec.runtimeTools or [ ]);
      sharedResourcePatch = ''
        ${lib.optionalString (builtins.elem "otter-render" closure) ''
          substituteInPlace ../otter-render/build.zig \
            --replace-fail \
              '        break :blk fontconfig_c.createModule();' \
              '        fontconfig_c.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.fontconfig}/include", });
        break :blk fontconfig_c.createModule();'

          # zigimg's scalar AVX2 fallback indexes a vector with a runtime
          # value. Zig 0.16 requires runtime indexing to go through an array.
          substituteInPlace ../otter-render/vendor/zigimg/src/simd.zig \
            --replace-fail \
              '        inline for (0..8) |i| res[i] = v[@as(u32, @bitCast(mask[i]))];' \
              '        const lanes: [8]i32 = v;
        inline for (0..8) |i| {
            const index = @as(u32, @bitCast(mask[i])) & 7;
            res[i] = lanes[index];
        }'

          substituteInPlace ../otter-render/src/font/resolve.zig \
            --replace-fail '/usr/share/fonts/otter-shell/' '${fontDir}'

          # Upstream carries distro-specific DejaVu/Liberation fallbacks. Keep
          # every build independent of an FHS host font installation.
          for source in \
            ../otter-render/src/quad_renderer.zig \
            ../otter-render/src/text/system.zig
          do
            substituteInPlace "$source" \
              --replace-fail '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf' '${fontDir}DejaVuSans.ttf' \
              --replace-fail '/usr/share/fonts/dejavu/DejaVuSans.ttf' '${fontDir}DejaVuSans.ttf' \
              --replace-fail '/usr/share/fonts/TTF/DejaVuSans.ttf' '${fontDir}DejaVuSans.ttf' \
              --replace-fail '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf' '${fontDir}DejaVuSans.ttf' \
              --replace-fail '/usr/share/fonts/TTF/LiberationSans-Regular.ttf' '${fontDir}DejaVuSans.ttf'
          done
        ''}
        ${lib.optionalString (builtins.elem "otter-wayland" closure) ''
          substituteInPlace ../otter-wayland/build.zig \
            --replace-fail \
              '    const xkbcommon = b.addTranslateC(.{' \
              '    const xkbcommon_c = b.addTranslateC(.{' \
            --replace-fail \
              '    }).createModule();' \
              '    });
    xkbcommon_c.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.libxkbcommon}/include", });
    const xkbcommon = xkbcommon_c.createModule();'
        ''}
        ${lib.optionalString (builtins.elem "otter-config-types" closure) ''
          substituteInPlace ../otter-config-types/src/term.zig \
            --replace-fail '/usr/share/fonts/otter-shell/' '${fontDir}' \
            --replace-fail 'paplay' '${termBellPlayer}' \
            --replace-fail '/usr/share/sounds/freedesktop/stereo/bell.oga' '${termBellSound}'
        ''}
        ${lib.optionalString (name == "otter-term") ''
          substituteInPlace src/app/metrics.zig \
            --replace-fail '/usr/share/fonts/otter-shell/' '${fontDir}'
          substituteInPlace src/app/effects.zig \
            --replace-fail 'paplay' '${termBellPlayer}' \
            --replace-fail '/usr/share/sounds/freedesktop/stereo/bell.oga' '${termBellSound}'
        ''}
        ${lib.optionalString (name == "otter-lock") ''
          substituteInPlace ../otter-config-types/src/lock.zig \
            --replace-fail '/usr/share/otter-shell/lock/otter-shell.png' \
            "$out/share/otter-shell/lock/otter-shell.png"
        ''}
      '';
      sourceFixup = packageSourceFixups.${name} or "";
    in
    mkZigPackage {
      pname = name;
      version = info.version;
      repoDir = name;
      inherit workspace zig extraSources;
      externalDeps = external.env;
      missingPins = (map (repo: repositories.${repo}.pin) (builtins.filter sourceMissing closure)) ++ missingExtraPins;
      missingLocks = external.missing;
      missingSystemDeps = sys.missing ++ unknownNativeTools ++ unknownRuntimeTools;
      buildInputs = sys.packages;
      nativeBuildInputs = nativeToolsResolved;
      runtimeInputs = runtimeToolsResolved;
      zigBuildFlags = [ "-Dcpu=baseline" ] ++ (spec.zigBuildFlags or [ ]);
      postPatch = sharedResourcePatch + sourceFixup + (spec.postPatch or "");
      postInstall = spec.postInstall or "";
      meta = {
        description = spec.description;
        homepage = "https://git.pika-os.com/otter-shell/${name}";
        license = lib.licenses.mit;
        platforms = spec.platforms or lib.platforms.linux;
        mainProgram = spec.executable;
      };
      passthru = {
        inherit closure;
        sourceRevision = info.revision;
        sourceRelease = info.release;
        sourceRevisions = lib.genAttrs closure (repo: (sourceInfo repo).revision);
        sourceReleases = lib.genAttrs closure (repo: (sourceInfo repo).release);
        tier = spec.tier;
      };
    };

  appPackages = lib.mapAttrs mkOne specs;
  availableOnHost = package: lib.meta.availableOn pkgs.stdenv.hostPlatform package;
  byTier = tier: builtins.filter availableOnHost (
    map (name: appPackages.${name}) (
      builtins.filter (name: specs.${name}.tier == tier) (builtins.attrNames specs)
    )
  );
  bundle = name: paths: pkgs.buildEnv {
    inherit name paths;
    pathsToLink = [ "/bin" "/share" ];
    ignoreCollisions = true;
  };

  core = bundle "otter-shell-core" ([ otterFonts ] ++ byTier "core" ++ byTier "helpers");
  extras = bundle "otter-shell-extras" (byTier "tools" ++ byTier "optional" ++ byTier "extras");
  system = bundle "otter-shell-system" (byTier "system");
  all = bundle "otter-shell-all" (
    [ otterFonts ] ++ builtins.filter availableOnHost (builtins.attrValues appPackages)
  );
in
appPackages // {
  otter-shell-fonts = otterFonts;
  otter-shell-core = core;
  otter-shell-extras = extras;
  otter-shell-system = system;
  otter-shell-all = all;
  default = core;
}
