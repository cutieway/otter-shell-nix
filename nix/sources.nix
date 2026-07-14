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
