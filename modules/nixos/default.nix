{ config, lib, pkgs, ... }:
let
  cfg = config.services.otter-shell;
in
{
  options.services.otter-shell = {
    enable = lib.mkEnableOption "system prerequisites for Otter Shell";
    installFonts = lib.mkOption { type = lib.types.bool; default = true; };
    fontPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "otter-shell" "fonts" ] null pkgs;
      defaultText = lib.literalExpression "pkgs.otter-shell.fonts or null";
    };
    enablePipeWire = lib.mkOption { type = lib.types.bool; default = true; };
    enableUPower = lib.mkOption { type = lib.types.bool; default = true; };
    enableNetworkManager = lib.mkOption { type = lib.types.bool; default = false; };
    enablePolkit = lib.mkOption { type = lib.types.bool; default = true; };
    enableLockPam = lib.mkOption { type = lib.types.bool; default = true; };
    enableRecorderKmsWrapper = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Install otter-rec-kms-server with cap_sys_admin via security.wrappers.";
    };
    recorderPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "otter-shell" "otter-rec" ] null pkgs;
      defaultText = lib.literalExpression "pkgs.otter-shell.otter-rec or null";
    };
  };

  config = lib.mkIf cfg.enable (lib.mkMerge [
    {
      assertions = [
        {
          assertion = !cfg.installFonts || cfg.fontPackage != null;
          message = "services.otter-shell.installFonts requires the Otter overlay or an explicit fontPackage";
        }
        {
          assertion = !cfg.enableRecorderKmsWrapper || cfg.recorderPackage != null;
          message = "services.otter-shell.enableRecorderKmsWrapper requires the Otter overlay or an explicit recorderPackage";
        }
      ];
      fonts.packages = lib.optional (cfg.installFonts && cfg.fontPackage != null) cfg.fontPackage;
    }
    (lib.mkIf cfg.enablePipeWire {
      services.pipewire = {
        enable = true;
        # Otter's terminal bell is played through paplay.
        pulse.enable = true;
      };
    })
    (lib.mkIf cfg.enableUPower { services.upower.enable = true; })
    (lib.mkIf cfg.enableNetworkManager { networking.networkmanager.enable = true; })
    (lib.mkIf cfg.enablePolkit {
      security.polkit.enable = true;
      # pkexec is a privileged NixOS wrapper, not a usable immutable store path.
      security.polkit.enablePkexecWrapper = lib.mkDefault true;
    })
    (lib.mkIf cfg.enableLockPam { security.pam.services.otter-lock = { }; })
    (lib.mkIf (cfg.enableRecorderKmsWrapper && cfg.recorderPackage != null) {
      # The package also contains an unprivileged binary with this name. Point
      # the recorder at the capability-bearing /run wrapper deterministically.
      environment.sessionVariables.OTTER_REC_KMS_SERVER = lib.mkDefault "/run/wrappers/bin/otter-rec-kms-server";
      security.wrappers.otter-rec-kms-server = {
        source = "${cfg.recorderPackage}/bin/otter-rec-kms-server";
        owner = "root";
        group = "root";
        permissions = "u+rx,g+x,o+x";
        capabilities = "cap_sys_admin+ep";
      };
    })
  ]);
}
