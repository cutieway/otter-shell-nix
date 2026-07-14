#ifndef OTTER_SHELL_NIX_CUDA_DRIVER_ABI_H
#define OTTER_SHELL_NIX_CUDA_DRIVER_ABI_H

/*
 * Otter Rec loads the CUDA driver with dlopen; it does not link the CUDA
 * toolkit.  Keep the small, stable driver-ABI surface used by that loader
 * local so building the open package does not require an unfree SDK.
 */
#include <stddef.h>
#include <stdint.h>

#ifndef CUDAAPI
#define CUDAAPI
#endif

typedef struct CUarray_st *CUarray;
typedef struct CUctx_st *CUcontext;
typedef struct CUgraphicsResource_st *CUgraphicsResource;
typedef struct CUstream_st *CUstream;
typedef uintptr_t CUdeviceptr;
typedef int CUresult;

typedef enum CUmemorytype_enum {
    CU_MEMORYTYPE_HOST = 0x01,
    CU_MEMORYTYPE_DEVICE = 0x02,
    CU_MEMORYTYPE_ARRAY = 0x03,
    CU_MEMORYTYPE_UNIFIED = 0x04,
} CUmemorytype;

typedef struct CUDA_MEMCPY2D_st {
    size_t srcXInBytes;
    size_t srcY;
    CUmemorytype srcMemoryType;
    const void *srcHost;
    CUdeviceptr srcDevice;
    CUarray srcArray;
    size_t srcPitch;
    size_t dstXInBytes;
    size_t dstY;
    CUmemorytype dstMemoryType;
    void *dstHost;
    CUdeviceptr dstDevice;
    CUarray dstArray;
    size_t dstPitch;
    size_t WidthInBytes;
    size_t Height;
} CUDA_MEMCPY2D;

enum {
    CUDA_SUCCESS = 0,
    CU_GRAPHICS_REGISTER_FLAGS_NONE = 0,
};

#endif
