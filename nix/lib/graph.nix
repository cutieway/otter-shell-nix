# Dependency-graph closure traversal for Otter Shell repositories.
#
# Given a repository name, computes its full transitive dependency closure
# including the repository itself, using a DFS that detects cycles and
# missing metadata. The repositories attribute set is expected to have the
# shape produced by nix/repositories.nix (generated):
#
#   "<repo>" = {
#     pin = "<npins-pin-name>";
#     directDeps = [ "<dep>" ... ];
#     ...
#   };

{ lib, repositories }:
let
  visit = stack: seen: name:
    if builtins.elem name stack then
      throw "otter-shell-nix: dependency cycle: ${lib.concatStringsSep " -> " (stack ++ [ name ])}"
    else if builtins.elem name seen then
      seen
    else if !builtins.hasAttr name repositories then
      throw "otter-shell-nix: repository metadata is missing '${name}'"
    else
      let
        next = builtins.foldl' (visit (stack ++ [ name ])) seen repositories.${name}.directDeps;
      in
      next ++ [ name ];
in
{
  # Produce the transitive closure of `name`, including the repo itself, in
  # topological order (deepest dependencies first).
  closureFor = name: builtins.foldl' (acc: dep: if builtins.elem dep acc then acc else acc ++ [ dep ]) [ ] (visit [ ] [ ] name);
}
