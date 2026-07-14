{
  gnutar,
  lib,
  runCommandLocal,
  zig,
}:

{
  source,
  zigHash,
  sourceIsArchive ? false,
}:

runCommandLocal "zig-cache-${builtins.substring 0 24 zigHash}.tar.gz"
  {
    nativeBuildInputs = [
      gnutar
      zig
    ];
  }
  ''
    export HOME="$TMPDIR/home"
    export SOURCE_DATE_EPOCH=1
    export ZIG_GLOBAL_CACHE_DIR="$TMPDIR/zig-global-cache"
    export ZIG_LOCAL_CACHE_DIR="$TMPDIR/zig-local-cache"

    mkdir -p \
      "$HOME" \
      "$ZIG_GLOBAL_CACHE_DIR/tmp" \
      "$ZIG_LOCAL_CACHE_DIR" \
      "$TMPDIR/work"
    touch "$TMPDIR/work/build.zig"

    ${lib.optionalString sourceIsArchive ''
      artifact=${lib.escapeShellArg source}
    ''}
    ${lib.optionalString (!sourceIsArchive) ''
      tar \
        --hard-dereference \
        --sort=name \
        --mtime=@1 \
        --owner=0 \
        --group=0 \
        --numeric-owner \
        -cf "$TMPDIR/source.tar" \
        -C ${lib.escapeShellArg source} \
        .
      artifact="$TMPDIR/source.tar"
    ''}

    cd "$TMPDIR/work"
    actual="$(zig fetch --global-cache-dir "$ZIG_GLOBAL_CACHE_DIR" "$artifact")"
    expected=${lib.escapeShellArg zigHash}

    if [[ "$actual" != "$expected" ]]; then
      echo "Zig package hash mismatch" >&2
      echo "  expected: $expected" >&2
      echo "  actual:   $actual" >&2
      exit 1
    fi

    cache_archive="$ZIG_GLOBAL_CACHE_DIR/p/$actual.tar.gz"
    if [[ ! -f "$cache_archive" ]]; then
      echo "Zig 0.16 did not create $cache_archive" >&2
      exit 1
    fi

    cp "$cache_archive" "$out"
  ''
