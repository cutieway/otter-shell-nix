{
  home = {
    username = "alice";
    homeDirectory = "/home/alice";
    stateVersion = "26.05";
  };

  wayland.windowManager.sway = {
    enable = true;
    # Sway is installed and wrapped by programs.sway in configuration.nix.
    package = null;
  };

  programs.otter-shell = {
    enable = true;
    swayIntegration.enable = true;
  };
}
