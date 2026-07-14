{ pkgs, lib }:
{
  repositories,
  sources,
  closure,
  extraSources ? [ ]
}:
let
  sourceFor = repo:
    let pin = repositories.${repo}.pin;
    in if builtins.hasAttr pin sources then sources.${pin} else
      pkgs.runCommand "missing-${repo}-source" { } ''
        mkdir -p "$out"
        printf '%s\n' "missing npins source: ${pin}" > "$out/MISSING_SOURCE"
      '';

  repoEntries = map (repo: {
    name = repo;
    path = sourceFor repo;
  }) closure;

  extraEntries = map (entry: {
    name = "__extra-${entry.pin}";
    path = if builtins.hasAttr entry.pin sources then sources.${entry.pin} else
      pkgs.runCommand "missing-${entry.pin}-source" { } ''
        mkdir -p "$out"
        printf '%s\n' "missing npins source: ${entry.pin}" > "$out/MISSING_SOURCE"
      '';
  }) extraSources;
in
pkgs.linkFarm "otter-workspace" (repoEntries ++ extraEntries)
