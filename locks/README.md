# Zig dependency locks

`tools/gen-locks.sh` writes one lock expression for each repository whose
reachable `build.zig.zon` files have URL dependencies. The generator replaces
`zon2nix` here because released `zon2nix` versions cannot parse Zig 0.16 ZON
files.

The generator:

1. starts from the repositories marked `hasRemoteDeps`;
2. follows vendored `.path` dependencies inside each repository;
3. prefetches every remote dependency with Nix;
4. recursively scans each fetched package's own `build.zig.zon`;
5. verifies every source against its Zig package hash with Zig 0.16; and
6. writes `sources.nix` plus the per-repository lock closures atomically.

Run it from the development shell after pinning sources:

```sh
nix develop .#bootstrap -c tools/gen-locks.sh
```

By default it obtains every repository with `npins get-path`; no local clone or
`repos/` directory is required. The current generated inventory contains 17
unique fixed-output external sources.

This inventory covers Otter's Zig 0.16 workspaces. Ghostty is an independently
pinned support source using Zig 0.15; `nix/packages.nix` calls the VT recipe and
`build.zig.zon.nix` shipped by that exact Ghostty revision instead of mixing its
cache format into these generated locks.

For an optional read-only inventory against local development clones, without
Nix fetches or file changes:

```sh
python3 tools/generate-zig-locks.py --source-root repos --inventory-only
```

A package receives the **union of the locks in its transitive repository
closure**.

The resulting merged derivation is linked directly as:

```text
$ZIG_GLOBAL_CACHE_DIR/p
```

Zig 0.16 stores packages as `p/<build.zig.zon-hash>.tar.gz`, not as the
hash-named source directories emitted by older `zon2nix` versions. Each fixed
source is therefore converted by `mk-cache-entry.nix`; that conversion fails if
either the Zig hash or the expected cache archive name differs.

Do not create a `p/deps` child. The generated link farms expose the `.tar.gz`
archives directly beneath `p`.

Each per-repository lock lists its complete expected closure. If an entry is
missing from `sources.nix`, evaluation fails with the missing Zig hashes instead
of allowing a sandboxed build to try the network. Do not publish an update until
`tools/gen-locks.sh` has completed and `python3 tools/check-framework.py` passes.
