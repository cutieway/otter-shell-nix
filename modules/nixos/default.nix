{ config, lib, options, pkgs, ... }:
let
  cfg = config.services.otter-shell;
  hasSeparatePkexecOption =
    lib.hasAttrByPath [ "security" "polkit" "enablePkexecWrapper" ] options;
in
{
  options.services.otter-shell = {
    enable = lib.mkEnableOption "system prerequisites for Otter Shell";
    installFonts = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether to install Otter Shell fonts system-wide via fonts.packages.";
    };
    fontPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "otter-shell" "fonts" ] null pkgs;
      defaultText = lib.literalExpression "pkgs.otter-shell.fonts or null";
      description = "Font package used by Otter Shell. Required when installFonts is true.";
    };
    enablePipeWire = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable PipeWire with PulseAudio support for Otter Shell's terminal bell and audio.";
    };
    enableUPower = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable UPower for power management integration.";
    };
    enableNetworkManager = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable NetworkManager for network management integration.";
    };
    enablePolkit = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Enable Polkit and its pkexec wrapper for privilege escalation.";
    };
    enableLockPam = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Create a PAM service for otter-lock (security.pam.services.otter-lock).";
    };
    enableRecorderKmsWrapper = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Install otter-rec-kms-server with cap_sys_admin via security.wrappers.";
    };
    recorderPackage = lib.mkOption {
      type = lib.types.nullOr lib.types.package;
      default = lib.attrByPath [ "otter-shell" "otter-rec" ] null pkgs;
      defaultText = lib.literalExpression "pkgs.otter-shell.otter-rec or null";
      description = "Package providing otter-rec-kms-server. Required when enableRecorderKmsWrapper is true.";
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
    (lib.mkIf cfg.enablePolkit (
      {
        security.polkit.enable = true;
      }
      // lib.optionalAttrs hasSeparatePkexecOption {
        # Recent NixOS releases expose this separately. Older releases create
        # the pkexec wrapper whenever Polkit is enabled.
        # ponytail: mkForce prevents silent weakening by downstream consumers.
        # A user who intentionally disables this can use mkForce themselves.
        security.polkit.enablePkexecWrapper = lib.mkForce true;
      }
    ))
    (lib.mkIf cfg.enableLockPam { security.pam.services.otter-lock = { }; })
    (lib.mkIf (cfg.enableRecorderKmsWrapper && cfg.recorderPackage != null) {
      # The package also contains an unprivileged binary with this name. Point
      # the recorder at the capability-bearing /run wrapper deterministically.
      # ponytail: mkForce prevents silent redirection of KMS server by downstream consumers.
      environment.sessionVariables.OTTER_REC_KMS_SERVER = lib.mkForce "/run/wrappers/bin/otter-rec-kms-server";
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
