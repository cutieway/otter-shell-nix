# Validation status

Generated from remote pinned release sources. Current graph: 45 Otter repos,
33 packages, 17 external Zig sources. Coordinated version `0.11.43`, minimum
Zig `0.16.0`. Full x86_64 package surface builds clean from npins alone.

Static checks cover dep graph, package-spec consistency, Zig cache layout,
patch semantics, Polkit wrapper, all source substitutions, and CUDA driver-ABI
boundary. See `MAINTENANCE.md` for release gate commands and `pipeline.py check`
for the live mechanical checks.
