{
  description = "Reproducible, workspace-aware Nix packaging for Otter Shell";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      lib = nixpkgs.lib;
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: lib.genAttrs systems (system: f system);
      sourceState = import ./nix/sources.nix { root = ./.; };
      pkgsFor = system: import nixpkgs { inherit system; };
      packagesFor = system: import ./nix/packages.nix {
        pkgs = pkgsFor system;
        root = ./.;
        inherit (sourceState) sources pins;
      };
      packageNames = builtins.attrNames (import ./nix/package-specs.nix);
    in
    {
      packages = forAllSystems packagesFor;

      overlays.default = final: _prev:
        let
          built = self.packages.${final.stdenv.hostPlatform.system};
          namespace = lib.genAttrs packageNames (name: built.${name}) // {
            fonts = built.otter-shell-fonts;
            core = built.otter-shell-core;
            extras = built.otter-shell-extras;
            system = built.otter-shell-system;
            all = built.otter-shell-all;
          };
        in
        {
          otter-shell = namespace;
          otter-shell-fonts = built.otter-shell-fonts;
        }
        // lib.genAttrs packageNames (name: built.${name});

      lib =
        let
          repositories = import ./nix/repositories.nix;
          graph = import ./nix/lib/graph.nix { inherit lib repositories; };
        in
        {
          inherit repositories;
          packageSpecs = import ./nix/package-specs.nix;
          repositoryClosure = graph.closureFor;
          mkPackages = args: import ./nix/packages.nix args;
        };

      homeManagerModules.default = import ./modules/home-manager;
      homeManagerModules.otter-shell = self.homeManagerModules.default;
      nixosModules.default = import ./modules/nixos;
      nixosModules.otter-shell = self.nixosModules.default;

      devShells = forAllSystems (system:
        let pkgs = pkgsFor system;
        in {
          default = pkgs.mkShellNoCC {
            packages = with pkgs; [ npins zig_0_16 jq curl git python3 shellcheck nixfmt ];
          };
          bootstrap = pkgs.mkShellNoCC {
            packages = with pkgs; [ npins zig_0_16 jq curl git python3 ];
          };
        });

      formatter = forAllSystems (system: (pkgsFor system).nixfmt);

      checks = forAllSystems (system:
        let pkgs = pkgsFor system;
        in {
          framework = pkgs.runCommand "otter-shell-framework-check" {
            nativeBuildInputs = [ pkgs.python3 pkgs.shellcheck ];
          } ''
            cd ${./.}
            python3 tools/pipeline.py check framework
            shellcheck tools/*.sh || true
            touch "$out"
          '';
        });
    };
}
