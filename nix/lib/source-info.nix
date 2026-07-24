# Source version/revision extraction from npins metadata.
#
# Otter Shell repos are pinned through npins. This function maps a
# repository name (kebab-case, e.g. "otter-bar") to its npins pin entry
# (which uses underscores: "otter_bar"), then extracts version, revision,
# and a Nix-compatible version string.
#
# Version conventions:
# - Release pins (tagged): strip the leading "v" prefix → "0.11.43"
# - Branch pins (main): "unstable-<shortRev>" (first 8 chars of commit)

{ lib, pins }:
repo:
let
  pinName = lib.replaceStrings [ "-" ] [ "_" ] repo;
  pin = if builtins.hasAttr pinName pins then pins.${pinName} else { };
  revision = pin.revision or null;
  release = pin.version or null;
  shortRevision = if revision == null then "unresolved" else builtins.substring 0 8 revision;
in
{
  inherit pinName revision release;
  version =
    if release != null then lib.removePrefix "v" release else "unstable-${shortRevision}";
}
