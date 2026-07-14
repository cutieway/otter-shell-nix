{
  fetchgit,
  fetchurl,
  fetchzip,
  gnutar,
  lib,
  linkFarm,
  runCommandLocal,
  zig,
}:

zigHashes:

let
  sources = import ./sources.nix {
    inherit fetchgit fetchurl fetchzip;
  };
  mkCacheEntry = import ./mk-cache-entry.nix {
    inherit gnutar lib runCommandLocal zig;
  };
  missing = builtins.filter (hash: !builtins.hasAttr hash sources) zigHashes;
in
assert lib.assertMsg (missing == [ ])
  "missing fixed-output Zig sources: ${lib.concatStringsSep ", " missing}";
linkFarm "zig-packages" (
  map (zigHash: {
    name = "${zigHash}.tar.gz";
    path = mkCacheEntry (sources.${zigHash} // { inherit zigHash; });
  }) zigHashes
)
