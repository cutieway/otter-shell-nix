{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    otter-shell.url = "github:cutieway/otter-shell-nix";
  };

  outputs = { nixpkgs, home-manager, otter-shell, ... }: {
    nixosConfigurations.host = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ({ ... }: { nixpkgs.overlays = [ otter-shell.overlays.default ]; })
        otter-shell.nixosModules.default
        home-manager.nixosModules.home-manager
        ./configuration.nix
        {
          home-manager = {
            useGlobalPkgs = true;
            useUserPackages = true;
            sharedModules = [ otter-shell.homeManagerModules.default ];
            users.alice = import ./home.nix;
          };
        }
      ];
    };
  };
}
