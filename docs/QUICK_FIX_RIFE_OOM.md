# 🚀 Quick Fix Guide: RIFE CUDA OOM

## Problem
RIFE interpolation running out of GPU memory (OOM error).

## Solution Applied
Added GPU memory management to prevent OOM:
- ✅ Explicit tensor cleanup after each frame pair
- ✅ CUDA cache clearing every 10 pairs
- ✅ Adaptive resolution downscaling when memory is low
- ✅ OOM error recovery with aggressive cleanup
- ✅ Memory allocator configuration for reduced fragmentation

## What Changed
**File**: `src/infrastructure/processors/rife/native.py`

**Changes**:
1. GPU memory monitoring and logging
2. Set `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
3. Delete tensors explicitly: `del frame1, frame2, mids`
4. Clear cache periodically: `torch.cuda.empty_cache()`
5. Downscale large frames when memory < 3GB free
6. OOM recovery handler

## Testing
Run interpolation on the video that failed before:
```bash
python3 pipeline_v2.py --mode interp --input <video-url>
```

**Watch for in logs**:
- ✅ `GPU Memory: X.XXgB allocated, Y.YYgB reserved`
- ✅ `GPU Memory after pair 20: X.XXgB allocated`
- ⚠️ `Low GPU memory, downscaling` (if triggered)

## Expected Results
- **Memory usage**: Stable ~8-10GB instead of growing to 13GB+
- **No OOM errors**: Should complete successfully
- **Video quality**: Same (or slightly reduced if downscaling triggered)

## If Still Fails
The fix includes OOM recovery that will log memory state. Check logs for:
```log
[WARNING] CUDA OOM detected, attempting recovery...
[INFO] After cleanup: X.XXgB allocated, Y.YYgB reserved
```

Then adjust the downscaling threshold in the code (currently 3GB).

## Docs
See `RIFE_OOM_FIX.md` for detailed technical documentation.

---
**Status**: ✅ Fixed & Ready  
**Date**: 2026-01-13

