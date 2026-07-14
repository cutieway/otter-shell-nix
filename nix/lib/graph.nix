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
  closureFor = name: lib.unique (visit [ ] [ ] name);
}
