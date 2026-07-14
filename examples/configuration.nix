{
  # Merge this example with the hardware and boot configuration for your host.
  system.stateVersion = "26.05";

  users.users.alice = {
    isNormalUser = true;
    extraGroups = [ "networkmanager" "wheel" ];
  };

  programs.sway.enable = true;

  services.otter-shell = {
    enable = true;
    enableNetworkManager = true;
  };
}
