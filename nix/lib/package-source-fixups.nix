# Per-repository source fixups applied before building each package.
# These are shell snippets run in postPatch, after the shared workspace fixups.
# Extracted from packages.nix for maintainability.
{ pkgs, lib }:
let
  llamaCppArchive = pkgs.fetchurl {
    url = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/b9789.tar.gz";
    hash = "sha256-tR8ToaZlaFX/bARZBB5hY8WdWo1jJUo8DlnDdc58LxU=";
  };
  # Compatibility with stock libapt-pkg: the vendored shim targets PikaOS's
  # patched apt (RemoveCacheLeftovers fast path). On stock apt the slow path
  # (always rebuild caches) is the safe superset, so rewrite it everywhere
  # the shim is compiled, i.e. otter-pkg and every package in its closure.
  aptShimCompat = ''
    substituteInPlace ../otter-pkg/vendor/apt-dpkg-libs/shim/src/acquire.cc \
      --replace-fail \
        '      pkgCacheFile::RemoveCacheLeftovers();' \
        '      pkgCacheFile::RemoveCaches();'
  '';
in
{
  otter-assist = ''
    # Forgejo release archives omit git submodule contents. Supply the exact
    # llama.cpp release expected by scripts/build-llama-static.sh.
    mkdir -p vendor/llama.cpp
    tar -xzf ${llamaCppArchive} \
      --strip-components=1 \
      -C vendor/llama.cpp
  '';
  otter-settings = ''
    substituteInPlace src/app_config.zig \
      --replace-fail '/usr/bin/tee' '${pkgs.coreutils}/bin/tee'
  '';
  otter-files = ''
    # translate-C needs the vendored headers' system counterparts from the
    # store rather than the FHS locations upstream develops against.
    substituteInPlace build.zig \
      --replace-fail \
        '    const libssh_c = libssh_translate.createModule();' \
        '    libssh_translate.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.libssh}/include" });
    const libssh_c = libssh_translate.createModule();' \
      --replace-fail \
        '    const webp_c = webp_translate.createModule();' \
        '    webp_translate.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.libwebp}/include" });
    const webp_c = webp_translate.createModule();'
  '';
  otter-rec = ''
    # Keep pkexec unresolved: on NixOS it must come from /run/wrappers/bin.
    substituteInPlace src/kms_client.zig \
      --replace-fail '"setcap"' '"${pkgs.libcap}/bin/setcap"'

    # The recorder dynamically loads libcuda rather than linking the CUDA
    # toolkit. Supply only the stable driver ABI declarations it uses.
    cp ${../cuda-driver-abi.h} src/cuda_driver_abi.h
    substituteInPlace src/av.h \
      --replace-fail \
        '#include <libavutil/hwcontext_cuda.h>' \
        '#include "cuda_driver_abi.h"
    #define CUDA_VERSION 12000
    #include <libavutil/hwcontext_cuda.h>'
    substituteInPlace src/gpu_bridge.h \
      --replace-fail '#include <cuda.h>' '#include "cuda_driver_abi.h"' \
      --replace-fail '#include <cudaGL.h>' ""
    substituteInPlace src/gpu_bridge.c \
      --replace-fail \
        'if (load_cuda_symbol2((void **)&p_cu_memcpy_2d_async, "cuMemcpy2DAsync_v2", "cuMemcpy2DAsync", err, err_len) < 0) return -1;' \
        'if (load_cuda_symbol((void **)&p_cu_memcpy_2d_async, "cuMemcpy2DAsync_v2", err, err_len) < 0) return -1;'
  '';
  otter-pkg = aptShimCompat;
  otter-first-setup = aptShimCompat;
  otter-welcome = aptShimCompat;
  otter-bench = ''
    # The Vulkan layer and GL hook translate system headers that live in
    # the store rather than FHS locations.
    substituteInPlace build.zig \
      --replace-fail \
        '        vulkan_types = tc.createModule();' \
        '        tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.vulkan-headers}/include" });
        vulkan_types = tc.createModule();' \
      --replace-fail \
        '        mod.addImport("gl", tc.createModule());' \
        '        tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.libglvnd}/include" });
        tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.xorg.libX11}/include" });
        tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.xorg.xorgproto}/include" });
        mod.addImport("gl", tc.createModule());' \
      --replace-fail \
        '        probe_mod.addImport("gl", probe_tc.createModule());' \
        '        probe_tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.libglvnd}/include" });
        probe_tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.xorg.libX11}/include" });
        probe_tc.addSystemIncludePath(.{ .cwd_relative = "${lib.getDev pkgs.xorg.xorgproto}/include" });
        probe_mod.addImport("gl", probe_tc.createModule());'
  '';
}
