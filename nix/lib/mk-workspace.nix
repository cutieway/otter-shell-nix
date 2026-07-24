# Build a link-farm workspace from Otter Shell source directories.
#
# Nix's fixed-output source fetchers (npins) produce independent store paths
# for each repository. Otter Shell's Zig build.zig expects a sibling-repository
# layout (all repos under a common parent). This function creates that layout
# as a link farm so the Zig build finds ../otter-* repositories as siblings.
#
# When a source is missing (not yet pinned), a stub derivation is substituted
# that writes "missing npins source: <pin>" to a MISSING_SOURCE file. This
# lets the framework pass evaluation even with an incomplete pin set, at the
# cost of failing later at build time if the stub is actually compiled.

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
