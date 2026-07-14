{ config, lib, pkgs, ... }:
let
  cfg = config.programs.otter-shell;
  specs = import ../../nix/package-specs.nix;
  names = builtins.attrNames specs;
  defaultPackage = name: lib.attrByPath [ "otter-shell" name ] null pkgs;
  enabledNames = builtins.filter (name: cfg.components.${name}.enable) names;
  enabledPackages = builtins.filter (p: p != null) (map (name: cfg.components.${name}.package) enabledNames);
  serviceNames = builtins.filter (name:
    specs.${name}.service
    && cfg.components.${name}.enable
    && cfg.components.${name}.package != null
  ) names;
  mkService = name:
    let
      component = cfg.components.${name};
      spec = specs.${name};
      assistArgs = lib.optionals (
        name == "otter-assist" && cfg.assist.model != null
      ) [
        "--model"
        (toString cfg.assist.model)
      ];
      args = (spec.serviceArgs or [ ]) ++ assistArgs ++ component.extraArgs;
      command = lib.escapeShellArgs ([ "${lib.getExe' component.package spec.executable}" ] ++ args);
    in
    lib.nameValuePair name {
      Unit = {
        Description = spec.description;
        PartOf = [ "graphical-session.target" ];
        After = [ "graphical-session.target" ];
      };
      Service = {
        ExecStart = command;
        Restart = "on-failure";
        RestartSec = 1;
      };
      Install.WantedBy = [ "graphical-session.target" ];
    };
in
{
  options.programs.otter-shell = {
    enable = lib.mkEnableOption "Otter Shell components";

    installFonts = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Install the Otter font package in the Home Manager profile.";
    };

    fontPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "otter-shell" "fonts" ] null pkgs;
      defaultText = lib.literalExpression "pkgs.otter-shell.fonts or null";
      description = "Font package used by Otter Shell.";
    };

    assist.model = lib.mkOption {
      type = lib.types.nullOr (lib.types.oneOf [ lib.types.path lib.types.str ]);
      default = null;
      example = lib.literalExpression "/var/lib/otter-assist/model.gguf";
      description = ''
        GGUF model passed to the otter-assist service. The model is deliberately
        not bundled with the package; use a Nix store path for an immutable
        model or a string for an externally managed file.
      '';
    };

    components = lib.genAttrs names (name: {
      enable = lib.mkOption {
        type = lib.types.bool;
        default = builtins.elem (specs.${name}.tier) [ "core" "helpers" ];
        description = "Enable ${name}.";
      };
      package = lib.mkOption {
        type = lib.types.nullOr lib.types.package;
        default = defaultPackage name;
        defaultText = lib.literalExpression "pkgs.otter-shell.${name} or null";
        description = "Package used for ${name}.";
      };
      extraArgs = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ ];
        description = "Extra command-line arguments for the user service, when this component has one.";
      };
    });

    swayIntegration = {
      enable = lib.mkEnableOption "Sway launcher and bar integration";
      disableSwayBars = lib.mkOption {
        type = lib.types.bool;
        default = true;
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = !cfg.installFonts || cfg.fontPackage != null;
        message = "programs.otter-shell.installFonts requires the Otter overlay or an explicit fontPackage";
      }
      {
        assertion = !cfg.components.otter-assist.enable || cfg.assist.model != null;
        message = "programs.otter-shell.components.otter-assist.enable requires programs.otter-shell.assist.model";
      }
    ] ++ map (name: {
      assertion = cfg.components.${name}.package != null;
      message = "programs.otter-shell.components.${name}.enable requires the Otter overlay or an explicit package";
    }) enabledNames;

    home.packages = enabledPackages ++ lib.optional (cfg.installFonts && cfg.fontPackage != null) cfg.fontPackage;

    systemd.user.services = builtins.listToAttrs (map mkService serviceNames);

    wayland.windowManager.sway = lib.mkIf cfg.swayIntegration.enable {
      config = {
        menu = lib.mkIf (
          cfg.components.otter-launcher.enable
          && cfg.components.otter-launcher.package != null
        ) "${lib.getExe cfg.components.otter-launcher.package}";
        bars = lib.mkIf (cfg.swayIntegration.disableSwayBars && cfg.components.otter-bar.enable) [ ];
      };
    };
  };
}
