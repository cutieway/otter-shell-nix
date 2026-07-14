# Hand-maintained application policy layered over generated repository metadata.
{
  "otter-assist" = {
    executable = "otter-assist";
    description = "Local inference daemon and CLI for Otter Assistant";
    tier = "extras";
    service = true;
    nativeTools = [ "cmake" "shaderc" ];
    extraSystemDeps = [ "spirv-headers" "vulkan-headers" "vulkan-loader" ];
    zigBuildFlags = [ "-Dembed_model=false" ];

    # Distribution builds keep the GGUF as data rather than embedding a second
    # copy in the daemon. nix/packages.nix injects the exact b9789 llama.cpp
    # source; keep the helper from ever updating it in the sandbox.
    postPatch = ''
      substituteInPlace scripts/build-llama-static.sh \
        --replace-fail \
          'git clone --depth 1 --branch "$tag" https://github.com/ggml-org/llama.cpp "$llama"' \
          'echo "otter-shell-nix: otter-assist pin is missing vendor/llama.cpp" >&2; exit 1' \
        --replace-fail 'elif [ -d "$llama/.git" ]; then' 'elif false; then' \
        --replace-fail '-march=x86-64-v3' '-march=x86-64'

      for source in \
        build.zig \
        src/main.zig \
        src/config.zig \
        ../otter-config-types/src/assist.zig \
        ../otter-config-types/src/root.zig
      do
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
  "otter-emoji" = {
    executable = "otter-emoji";
    description = "Emoji picker helper";
    tier = "helpers";
    service = false;
    runtimeTools = [ "wl-clipboard" ];
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
    postPatch = ''
      # otter-hypr main still uses the pre-CSD namespace, while the coordinated
      # 0.11.43 theme moved titlebar colors into Theme.csd.
      substituteInPlace src/draw.zig \
        --replace-fail 'theme.decorations.' 'theme.csd.'
    '';
  };
  "otter-idle" = {
    executable = "otter-idle";
    description = "Wayland idle management daemon";
    tier = "core";
    service = true;
    runtimeTools = [ "systemd" ];
  };
  "otter-jade" = {
    executable = "otter-jade";
    description = "Animated desktop pet";
    tier = "optional";
    service = true;
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
  "otter-pick" = {
    executable = "otter-pick";
    description = "Wayland color picker";
    tier = "tools";
    service = false;
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
        --replace-fail 'git -C "$vendor" submodule update --init --recursive' ':'

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
    # Upstream currently hardcodes SSE4.2/F16C/FMA/BMI2/AVX/AVX2 flags.
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
}
