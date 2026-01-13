# 🔧 RIFE CUDA OOM Fix - Summary

## Problem
```
torch.OutOfMemoryError: CUDA out of memory. 
Tried to allocate 2.99 GiB. GPU 0 has a total capacity of 15.70 GiB 
of which 2.31 GiB is free. Process has 13.22 GiB memory in use.
```

## Root Cause
RIFE interpolation was accumulating GPU memory without cleanup:
- No explicit tensor deletion
- No CUDA cache clearing between frames
- No adaptive resolution scaling for low memory
- Memory fragmentation over time

## Solution Implemented

### 1. **GPU Memory Monitoring** ✅
Added comprehensive memory logging:
```python
# At model load time
gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
self.logger.info(f"GPU Memory: {gpu_mem_allocated:.2f}GB allocated")
```

### 2. **Memory Allocator Configuration** ✅
Set PyTorch CUDA allocator to reduce fragmentation:
```python
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
```

### 3. **Explicit Tensor Cleanup** ✅
Delete tensors immediately after use:
```python
# After processing each frame pair
del frame1, frame2, mids
```

### 4. **Periodic CUDA Cache Clearing** ✅
Clear GPU cache every 10 pairs:
```python
if torch.cuda.is_available() and (idx + 1) % 10 == 0:
    torch.cuda.empty_cache()
```

### 5. **Adaptive Resolution Downscaling** ✅
Automatically downscale when memory is low:
```python
# Check available memory
gpu_mem_free = gpu_mem_total - gpu_mem_allocated
if gpu_mem_free < 3GB or estimated_needed > 80% of free:
    scale_factor = 0.5  # Downscale to 50%
    # Process at lower resolution
    # Upscale results back to original
```

### 6. **OOM Recovery** ✅
Aggressive cleanup on OOM error:
```python
if "out of memory" in str(e).lower():
    del frame1, frame2
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    # Log memory state and retry guidance
```

## Changes Made

### Modified Files (1)
- `src/infrastructure/processors/rife/native.py`

### Key Modifications

#### 1. Model Loading (Line ~335)
```python
# Added GPU memory info logging
if torch.cuda.is_available():
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    self.logger.info(f"GPU: {gpu_name}")
    self.logger.info(f"GPU Memory: {gpu_mem_total:.2f}GB total")
    
    # Set memory allocator config
    os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
```

#### 2. Interpolation Start (Line ~745)
```python
# Log initial GPU memory state
if torch.cuda.is_available():
    gpu_mem_total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
    gpu_mem_reserved = torch.cuda.memory_reserved(0) / 1024**3
    self.logger.info(f"GPU Memory: {gpu_mem_allocated:.2f}GB allocated...")
```

#### 3. Frame Pair Processing (Line ~548)
```python
# Determine device FIRST (before memory check)
model_dev = getattr(self, 'model_device', None) or self.device
model_dev = torch.device(str(model_dev))

# Check available GPU memory and adaptively downscale
scale_factor = 1.0
if torch.cuda.is_available() and model_dev.type == 'cuda':
    gpu_mem_free = gpu_mem_total - gpu_mem_allocated
    
    # Estimate memory needed
    frame_size_bytes = orig_h * orig_w * 3 * 4  # float32
    estimated_needed = frame_size_bytes * 8
    
    # Downscale if needed
    if gpu_mem_free < 3GB or estimated_needed > 80% free:
        if orig_h > 1080 or orig_w > 1920:
            scale_factor = 0.5
            self.logger.warning("Downscaling to save memory")
```

#### 4. After Processing Each Pair (Line ~825)
```python
# MEMORY CLEANUP: Explicitly delete tensors
del frame1, frame2, mids

# Clear CUDA cache every 10 pairs
if torch.cuda.is_available() and (idx + 1) % 10 == 0:
    torch.cuda.empty_cache()
    
    # Log memory every 20 pairs
    if (idx + 1) % 20 == 0:
        gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
        self.logger.debug(f"GPU Memory after pair {idx+1}: {gpu_mem_allocated:.2f}GB")
```

#### 5. OOM Error Handling (Line ~860)
```python
except Exception as e:
    # If CUDA OOM, try to recover
    if torch.cuda.is_available() and "out of memory" in str(e).lower():
        self.logger.warning("CUDA OOM detected, attempting recovery...")
        
        # Aggressive cleanup
        try:
            del frame1, frame2
        except:
            pass
        
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        
        # Log memory state
        gpu_mem_allocated = torch.cuda.memory_allocated(0) / 1024**3
        self.logger.info(f"After cleanup: {gpu_mem_allocated:.2f}GB allocated")
        
        # Set env variable for fragmentation
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
    
    raise
```

#### 6. Interpolation with Downscaling (Line ~620)
```python
# Apply adaptive downscaling if needed
if scale_factor < 1.0:
    import torch.nn.functional as F
    new_h = int(orig_h * scale_factor)
    new_w = int(orig_w * scale_factor)
    # Make dimensions even
    new_h = new_h - (new_h % 2)
    new_w = new_w - (new_w % 2)
    frame1 = F.interpolate(frame1, size=(new_h, new_w), mode='bilinear')
    frame2 = F.interpolate(frame2, size=(new_h, new_w), mode='bilinear')

# ... process at lower resolution ...

# Upscale back to original
if scale_factor < 1.0:
    mid = F.interpolate(mid, size=(orig_h, orig_w), mode='bilinear')
```

## Expected Impact

### Memory Usage
- **Before**: Continuously growing, reaching ~13GB
- **After**: Stable ~8-10GB with periodic cleanup

### Performance
- **No downscaling**: Same speed (just better memory management)
- **With downscaling** (when needed): Slightly slower due to up/downscaling, but prevents OOM

### Reliability
- **Before**: OOM errors on large videos or GPUs with <16GB VRAM
- **After**: Should handle videos on GPUs with as little as 8GB VRAM

## Testing Recommendations

### 1. Test on Different GPUs
- **8GB VRAM**: Should work with downscaling
- **12GB VRAM**: Should work without downscaling
- **16GB+ VRAM**: Should work smoothly

### 2. Test on Different Resolutions
- **720p (1280x720)**: Should work fine
- **1080p (1920x1080)**: Should work with cleanup
- **1440p (2560x1440)**: May trigger downscaling
- **4K (3840x2160)**: Will trigger downscaling on <16GB GPUs

### 3. Test on Different Video Lengths
- **Short (< 100 frames)**: Should complete without issues
- **Medium (100-500 frames)**: Memory cleanup should be visible in logs
- **Long (500+ frames)**: Should show periodic cache clearing

## Monitoring

### Success Indicators ✅
```log
[INFO] GPU Memory: 8.5GB allocated, 13.2GB reserved, 15.7GB total
[DEBUG] GPU Memory after pair 20: 8.7GB allocated, 13.5GB reserved
[INFO] Processed 191/191 pairs (100.0%) | 7.81 fps
```

### Warning Signs ⚠️
```log
[WARNING] ⚠️ Low GPU memory (2.5GB free), downscaling 1920x1080 → 960x540
[WARNING] CUDA OOM detected, attempting recovery...
```

### Failure (Should Not Happen) ❌
```log
[ERROR] torch.OutOfMemoryError: CUDA out of memory
```

## Rollback Plan

If issues occur:
```bash
git diff src/infrastructure/processors/rife/native.py
git checkout src/infrastructure/processors/rife/native.py
```

## Additional Optimizations (Future)

1. **Batch Processing**: Process multiple frame pairs in parallel (requires more code changes)
2. **Mixed Precision**: Use FP16 instead of FP32 (requires model support)
3. **Gradient Checkpointing**: Trade compute for memory (for very large resolutions)
4. **Streaming**: Process video in chunks instead of all at once

## Compatibility

- **PyTorch**: 1.9+ (for `expandable_segments` config)
- **CUDA**: 11.0+ (for modern memory management)
- **GPU**: Any NVIDIA GPU with CUDA support

## Status

✅ **IMPLEMENTED & READY TO TEST**

- [x] GPU memory monitoring
- [x] Memory allocator configuration
- [x] Explicit tensor cleanup
- [x] Periodic cache clearing
- [x] Adaptive downscaling
- [x] OOM error recovery
- [x] Enhanced logging

## Next Steps

1. Test on a problematic video that caused OOM before
2. Monitor logs for memory usage patterns
3. Verify video quality is maintained
4. Adjust downscaling threshold if needed (currently 3GB free)

---

**Created**: 2026-01-13  
**Status**: Ready for Testing  
**Priority**: HIGH (User-facing issue)

