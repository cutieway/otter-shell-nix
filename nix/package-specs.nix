# Hand-maintained application policy layered over generated repository metadata.
{
  "otter-assist" = {
    executable = "otter-assist";
    description = "Local inference daemon and CLI for Otter Assistant";
    tier = "extras";
    service = true;
    nativeTools = [ "cmake" "shaderc" ];
    extraSystemDeps = [ "spirv-headers" "vulkan-headers" "vulkan-loader" ];

    # Upstream no longer embeds the model: the daemon always loads the
    # external GGUF. nix/packages.nix injects the exact b9789 llama.cpp
    # source; keep the helper from ever updating it in the sandbox.
    postPatch = ''
      substituteInPlace scripts/build-llama-static.sh \
        --replace-fail \
          'git clone --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$llama"' \
          'echo "otter-shell-nix: otter-assist pin is missing vendor/llama.cpp" >&2; exit 1' \
        --replace-fail 'elif [ -d "$llama/.git" ]; then' 'elif false; then' \
        --replace-fail '-march=x86-64-v3' '-march=x86-64'

      for source in \
        src/main.zig \
        src/config.zig \
        ../otter-config-types/src/assist.zig \
        ../otter-config-types/src/root.zig
      do
        # NB: build.zig is intentionally absent. It installs to prefix-relative
        # lib/otter-assist/ since 0.11.113, so no FHS rewrite is needed there.
        substituteInPlace "$source" \
          --replace-fail '/usr/lib/otter-assist/' "$out/lib/otter-assist/"
      done
    '';

    # Upstream's llama runtime currently selects an x86-64 compiler target.
    platforms = [ "x86_64-linux" ];
  };
  "otter-assistant" = {
    executable = "otter-assistant";
    description = "Otter Assistant graphical client";
    tier = "extras";
    service = false;
    # The packaged local backend is currently x86-64-only, and the GUI speaks
    # to that backend through a per-display Unix socket.
    platforms = [ "x86_64-linux" ];
  };
  "otter-bench" = {
    executable = "otter-bench";
    description = "Performance HUD, telemetry and benchmark suite";
    tier = "tools";
    service = false;
    # The Vulkan layer translate step needs registry headers; the loader
    # itself arrives through the workspace system libraries.
    extraSystemDeps = [ "libX11" "vulkan-headers" "xorgproto" ];
    # The privileged hardware helper stays compiled out: it needs setuid
    # elevation that NixOS manages outside the store.
    zigBuildFlags = [ "-Dhardware-service=false" ];
    postPatch = ''
      # otter-bench v0.1.x predates the semantic theme roles: remap the
      # retired namespaces onto their 0.11.113 equivalents.
      substituteInPlace apps/desktop/src/app.zig \
        --replace-fail 'self.theme.fonts.font_family' 'self.theme.globals.font_family' \
        --replace-fail 'new_theme.fonts.font_family' 'new_theme.globals.font_family' \
        --replace-fail 'self.theme.decorations.prefered_decoration_type != .none' 'self.theme.layout.decoration != .none' \
        --replace-fail 'self.theme.colors.background_opaque' 'self.theme.colors.background'
      for page in \
        apps/desktop/src/pages/hud.zig \
        apps/desktop/src/pages/placeholder.zig \
        apps/desktop/src/ui/kit.zig
      do
        substituteInPlace "$page" \
          --replace-fail 'theme.popup.border_radius' 'theme.layout.panel_radius'
      done
      # The fromTheme bridge maps otter_theme tokens onto bench-local roles.
      substituteInPlace libs/config/src/theme_colors.zig \
        --replace-fail 'convert(c.critical)' 'convert(c.danger)' \
        --replace-fail 'convert(c.background_opaque)' 'convert(c.background)' \
        --replace-fail 'convert(theme.popup.border)' 'convert(theme.colors.border)'
      # The retired theme.surfaces roles map onto semantic colors. Order
      # matters: surface_alt must precede surface (substring overlap).
      for target in \
        apps/desktop/src/pages/hud.zig \
        apps/desktop/src/ui/kit.zig
      do
        substituteInPlace "$target" \
          --replace-fail 'theme.surfaces.border_subtle' 'theme.colors.border' \
          --replace-fail 'theme.surfaces.destructive' 'theme.colors.danger' \
          --replace-fail 'theme.surfaces.recessed' 'theme.colors.background' \
          --replace-fail 'theme.surfaces.surface_alt' 'theme.colors.surface_alt' \
          --replace-fail 'theme.surfaces.surface' 'theme.colors.surface'
      done
      substituteInPlace apps/desktop/src/pages/placeholder.zig \
        --replace-fail 'theme.surfaces.border_subtle' 'theme.colors.border' \
        --replace-fail 'theme.surfaces.surface' 'theme.colors.surface'
      substituteInPlace apps/desktop/src/shell_ui.zig \
        --replace-fail 'theme.surfaces.surface_alt' 'theme.colors.surface_alt'
      substituteInPlace apps/desktop/src/pages/hud_props.zig \
        --replace-fail 'theme.surfaces.surface' 'theme.colors.surface'
      # Button radii live on Layout now, not Spacing.
      substituteInPlace apps/desktop/src/pages/hud.zig \
        --replace-fail 'theme.spacing.button_border_radius' 'theme.layout.control_radius'
      substituteInPlace apps/desktop/src/shell_ui.zig \
        --replace-fail 'theme.spacing.button_border_radius' 'theme.layout.control_radius'
      substituteInPlace apps/desktop/src/ui/kit.zig \
        --replace-fail 'theme.spacing.button_border_radius' 'theme.layout.control_radius'
    '';
  };
  "otter-bar" = {
    executable = "otter-bar";
    description = "Wayland status bar";
    tier = "core";
    service = true;
  };
  "otter-cal" = {
    executable = "otter-cal";
    description = "Calendar and agenda helper";
    tier = "helpers";
    service = false;
  };
  "otter-calc" = {
    executable = "otter-calc";
    description = "Calculator helper";
    tier = "helpers";
    service = false;
    runtimeTools = [ "wl-clipboard" ];
  };
  "otter-clicker" = {
    executable = "otter-clicker";
    description = "Wayland automatic click tool";
    tier = "tools";
    service = false;
  };
  "otter-clip" = {
    executable = "otter-clip";
    description = "Clipboard manager and wl-copy/wl-paste provider";
    tier = "core";
    service = true;
    serviceArgs = [ "daemon" ];
    runtimeTools = [ "xdg-utils" ];
  };
  "otter-cue" = {
    executable = "otter-cue";
    description = "Synthesized desktop interaction sounds";
    tier = "helpers";
    service = false;
  };
  "otter-dock" = {
    executable = "otter-dock";
    description = "Wayland application dock";
    tier = "core";
    service = true;
  };
  "otter-emoji" = {
    executable = "otter-emoji";
    description = "Emoji picker helper";
    tier = "helpers";
    service = false;
    runtimeTools = [ "wl-clipboard" ];
  };
  "otter-files" = {
    executable = "otter-files";
    description = "Wayland file manager";
    tier = "core";
    service = false;
    runtimeTools = [ "xdg-utils" ];
    postPatch = ''
      substituteInPlace src/file_manager_service.zig \
        --replace-fail '/usr/bin/otter-files' "$out/bin/otter-files"
    '';
  };
  "otter-first-setup" = {
    executable = "otter-first-setup";
    description = "First-run setup wizard";
    tier = "system";
    service = false;
    # otter-pkg vendors an apt-dpkg-libs CMake shim that configures at
    # compile time for every package in its closure.
    nativeTools = [ "cmake" ];
  };
  "otter-greeter" = {
    executable = "otter-greeterd";
    description = "Otter display manager and greeter";
    tier = "system";
    service = false;
  };
  "otter-hypr" = {
    executable = "otter-hypr-titlebar";
    description = "Hyprland titlebar companion";
    tier = "optional";
    service = true;
    runtimeTools = [ "hyprland" ];
  };
  "otter-idle" = {
    executable = "otter-idle";
    description = "Wayland idle management daemon";
    tier = "core";
    service = true;
    runtimeTools = [ "systemd" ];
  };
  "otter-installer" = {
    executable = "otter-installer";
    description = "PikaOS system installer";
    tier = "system";
    service = false;
  };
  "otter-jade" = {
    executable = "otter-jade";
    description = "Animated desktop pet";
    tier = "optional";
    service = true;
  };
  "otter-keybindhelp" = {
    executable = "otter-keybindhelp";
    description = "Keyboard shortcut reference";
    tier = "helpers";
    service = false;
  };
  "otter-launcher" = {
    executable = "otter-launcher";
    description = "Wayland application launcher";
    tier = "core";
    service = false;
    runtimeTools = [ "xdg-utils" ];
  };
  "otter-lock" = {
    executable = "otter-lock";
    description = "Wayland session lock";
    tier = "core";
    service = false;
  };
  "otter-logout" = {
    executable = "otter-logout";
    description = "Wayland power menu";
    tier = "core";
    service = false;
    runtimeTools = [ "systemd" ];
  };
  "otter-monitor" = {
    executable = "otter-monitor";
    description = "System monitor";
    tier = "tools";
    service = false;
  };
  "otter-nightlight" = {
    executable = "otter-nightlight";
    description = "Night-light color temperature daemon";
    tier = "core";
    service = true;
  };
  "otter-note" = {
    executable = "otter-note";
    description = "Sticky Markdown notes";
    tier = "tools";
    service = false;
  };
  "otter-notifications" = {
    executable = "otter-notifications";
    description = "Desktop notification daemon";
    tier = "core";
    service = true;
  };
  "otter-osd" = {
    executable = "otter-osd";
    description = "On-screen display daemon";
    tier = "core";
    service = true;
  };
  "otter-overview" = {
    executable = "otter-overview";
    description = "Workspace overview and window switcher";
    tier = "core";
    service = true;
  };
  "otter-pick" = {
    executable = "otter-pick";
    description = "Wayland color picker";
    tier = "tools";
    service = false;
  };
  "otter-pkg" = {
    executable = "otter-pkg";
    description = "Software manager for Debian-family systems";
    tier = "system";
    service = false;
    # The vendored apt-dpkg-libs shim configures with CMake at compile time.
    nativeTools = [ "cmake" ];
    postPatch = ''
      substituteInPlace src/onboarding.zig \
        --replace-fail '/usr/bin/otter-pkg' "$out/bin/otter-pkg"
      substituteInPlace data/polkit-1/actions/org.otter_shell.otter_pkg.policy \
        --replace-fail '/usr/bin/otter-pkg' "$out/bin/otter-pkg"
    '';
  };
  "otter-polkit" = {
    executable = "otter-polkit";
    description = "Polkit authentication agent";
    tier = "core";
    service = true;
  };
  "otter-rec" = {
    executable = "otter-rec";
    description = "Wayland screen recorder";
    tier = "tools";
    service = false;
    extraSystemDeps = [ "ffmpeg" "libdrm" "libglvnd" ];
  };
  "otter-screenshot" = {
    executable = "otter-screenshot";
    description = "Wayland screenshot tool";
    tier = "tools";
    service = false;
    runtimeTools = [ "wl-clipboard" ];
  };
  "otter-search" = {
    executable = "otter-search";
    description = "Desktop search daemon";
    tier = "core";
    service = true;
  };
  "otter-settings" = {
    executable = "otter-settings";
    description = "Graphical settings editor";
    tier = "core";
    service = false;
    runtimeTools = [ "coreutils" ];
  };
  "otter-shot" = {
    executable = "otter-shot";
    description = "Product-shot composer";
    tier = "tools";
    service = false;
    runtimeTools = [ "wl-clipboard" ];
  };
  "otter-taskbar" = {
    executable = "otter-taskbar";
    description = "Windows-style taskbar for Wayland";
    tier = "core";
    service = true;
  };
  "otter-term" = {
    executable = "otter-term";
    description = "Otter terminal emulator";
    tier = "core";
    service = false;
    extraSystemDeps = [ "libghostty-vt" ];
    runtimeTools = [ "xdg-utils" ];
  };
  "otter-theme-gen" = {
    executable = "otter-theme-gen";
    description = "Wallpaper-reactive theme generator";
    tier = "core";
    service = true;
  };
  "otter-timer" = {
    executable = "otter-timer";
    description = "Countdown timer helper";
    tier = "helpers";
    service = false;
    runtimeTools = [ "bash" ];
  };
  "otter-transcribe" = {
    executable = "otter-transcribe";
    description = "Local speech transcription daemon";
    tier = "extras";
    service = true;
    nativeTools = [ "cmake" "git" ];
    runtimeTools = [ "wl-clipboard" ];
    extraSources = [
      { pin = "parakeet_cpp"; target = "vendor/parakeet.cpp"; }
    ];
    postPatch = ''
      # Upstream's helper clones at build time. Nix provides the pinned tree above.
      substituteInPlace scripts/build-parakeet-static.sh \
        --replace-fail 'if [ ! -d "$vendor/.git" ]; then' 'if [ ! -f "$vendor/CMakeLists.txt" ]; then' \
        --replace-fail 'git clone https://github.com/mudler/parakeet.cpp "$vendor"' 'echo "missing pinned parakeet.cpp source" >&2; exit 1' \
        --replace-fail 'git -C "$vendor" submodule update --init --recursive' ':' \
        --replace-fail '-march=x86-64-v3' '-march=x86-64'

      # Upstream split sound-event detection and speaker ID into their own
      # static archives; the Zig link lists archives explicitly, so follow.
      substituteInPlace build.zig \
        --replace-fail '"vendor/parakeet.cpp/build-static/libparakeet.a",' \
        '"vendor/parakeet.cpp/build-static/libparakeet.a",
    "vendor/parakeet.cpp/build-static/third_party/ced.cpp/libced.a",
    "vendor/parakeet.cpp/build-static/third_party/voice-detect.cpp/libvoicedetect.a",' \
        --replace-fail 'addCompilerRuntimeArchive(b, artifact, "gcc", "libgcc_eh.a", "gcc_eh");' \
        'addCompilerRuntimeArchive(b, artifact, "gcc", "libgcc_eh.a", "gcc_eh");
    addCompilerRuntimeArchive(b, artifact, "gcc", "libgcc.a", "gcc_s");'

      # npins correctly strips Git metadata, so parakeet's Git-dependent CMake
      # helper cannot apply the patches shipped alongside its ggml submodule.
      # Apply that exact patch series as ordinary source patches instead.
      ggml_patches=(vendor/parakeet.cpp/third_party/ggml-patches/*.patch)
      if [[ ! -e "''${ggml_patches[0]}" ]]; then
        echo "otter-shell-nix: parakeet.cpp contains no ggml patch series" >&2
        exit 1
      fi
      for ggml_patch in "''${ggml_patches[@]}"; do
        patch -d vendor/parakeet.cpp/third_party/ggml -p1 < "$ggml_patch"
      done
      substituteInPlace vendor/parakeet.cpp/CMakeLists.txt \
        --replace-fail \
          'if(BASH_EXECUTABLE AND EXISTS "''${CMAKE_SOURCE_DIR}/scripts/apply_ggml_patches.sh")' \
          'if(FALSE)'
    '';
  };
  "otter-vox" = {
    executable = "otter-vox";
    description = "Local text-to-speech CLI";
    tier = "extras";
    service = false;
    # scripts/build-ggml.sh configures the vendored ggml tree with CMake and
    # compiles the Vulkan backend, so the ggml toolchain rides along.
    nativeTools = [ "cmake" "shaderc" ];
    extraSystemDeps = [ "spirv-headers" "vulkan-headers" "vulkan-loader" ];
    # Upstream's ggml runtime compiles with -march=x86-64-v3
    # (scripts/build-ggml.sh), so AVX2-class CPUs are required.
    platforms = [ "x86_64-linux" ];
  };
  "otter-wallpaper" = {
    executable = "otter-wallpaper";
    description = "Wayland wallpaper daemon";
    tier = "core";
    service = true;
  };
  "otter-weather" = {
    executable = "otter-weather";
    description = "Weather widget and popup";
    tier = "optional";
    service = true;
  };
  "otter-welcome" = {
    executable = "otter-welcome";
    description = "Welcome and getting-started application";
    tier = "system";
    service = false;
    # See otter-first-setup: the otter-pkg apt shim needs CMake at build time.
    nativeTools = [ "cmake" ];
  };
}

# Deferred repositories (pinned, in the dependency graph or ignored, but
# with no package spec yet):
# - otter-browser: needs WPEWebKit-2.0, which nixpkgs does not provide.
# - otter-shell-plugins: examples-only .so plugins, not a shippable product.
