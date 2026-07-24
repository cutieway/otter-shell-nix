# Per-repository source fixups applied before building each package.
# These are shell snippets run in postPatch, after the shared workspace fixups.
# Extracted from packages.nix for maintainability.
{ pkgs, lib }:
let
  llamaCppArchive = pkgs.fetchurl {
    url = "https://github.com/ggml-org/llama.cpp/archive/refs/tags/b9789.tar.gz";
    hash = "sha256-tR8ToaZlaFX/bARZBB5hY8WdWo1jJUo8DlnDdc58LxU=";
  };
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
}
