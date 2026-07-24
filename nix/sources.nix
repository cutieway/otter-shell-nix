# Load npins pin metadata and source store paths.
#
# This separates the two sides of npins:
# - pins: metadata from npins/sources.json (revision, version, url)
# - sources: the actual store paths of fetched sources via npins/default.nix
#
# The `initialized` flag lets consumers (like the bootstrap shell) degrade
# gracefully when npins has not yet been set up on a fresh fork.

{ root }:
let
  pinsPath = root + "/npins/sources.json";
  loaderPath = root + "/npins/default.nix";
  pinsJson = if builtins.pathExists pinsPath then builtins.fromJSON (builtins.readFile pinsPath) else { pins = { }; };
in
{
  pins = pinsJson.pins or { };
  sources = if builtins.pathExists loaderPath then import (root + "/npins") else { };
  initialized = builtins.pathExists loaderPath && builtins.pathExists pinsPath;
}
