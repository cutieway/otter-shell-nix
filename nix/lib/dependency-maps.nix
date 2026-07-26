# Maps from Otter dependency names to nixpkgs packages.
# Extracted from packages.nix for maintainability.
{ pkgs, lib, ghosttyVt }:
{
  systemDependencyMap = {
    "wayland-client" = { name = "wayland"; package = pkgs.wayland; };
    xkbcommon = { name = "libxkbcommon"; package = pkgs.libxkbcommon; };
    fontconfig = { name = "fontconfig"; package = pkgs.fontconfig; };
    pam = { name = "pam"; package = pkgs.pam; };
    "ghostty-vt" = {
      name = "libghostty-vt";
      package = ghosttyVt;
    };
    libavcodec = { name = "ffmpeg"; package = pkgs.ffmpeg; };
    libavformat = { name = "ffmpeg"; package = pkgs.ffmpeg; };
    libavutil = { name = "ffmpeg"; package = pkgs.ffmpeg; };
    libswscale = { name = "ffmpeg"; package = pkgs.ffmpeg; };
    libdrm = { name = "libdrm"; package = pkgs.libdrm; };
    egl = { name = "libglvnd"; package = pkgs.libglvnd; };
    glesv2 = { name = "libglvnd"; package = pkgs.libglvnd; };

  };

  namedDependencyMap = {
    ffmpeg = pkgs.ffmpeg;
    libdrm = pkgs.libdrm;
    libglvnd = pkgs.libglvnd;
    "libghostty-vt" = ghosttyVt;
    "spirv-headers" = pkgs.spirv-headers;
    "vulkan-headers" = pkgs.vulkan-headers;
    "vulkan-loader" = pkgs.vulkan-loader;
  };

  nativeToolMap = {
    cmake = pkgs.cmake;
    git = pkgs.git;
    shaderc = lib.getBin pkgs.shaderc;
  };

  runtimeToolMap = {
    bash = pkgs.bash;
    coreutils = pkgs.coreutils;
    hyprland = pkgs.hyprland;
    systemd = pkgs.systemd;
    "wl-clipboard" = pkgs.wl-clipboard;
    "xdg-utils" = pkgs.xdg-utils;
  };
}
