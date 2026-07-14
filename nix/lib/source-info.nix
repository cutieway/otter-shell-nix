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
