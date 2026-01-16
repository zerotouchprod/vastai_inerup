# EMERGENCY ProPainter OOM Fix - January 15, 2026

## Critical Issue

ProPainter continues to crash with OOM even after initial fixes:
- Processing at 352x640 resolution
- 10 frames per chunk
- 24GB RTX 3090 GPU

**Error Location:** `/opt/ProPainter/RAFT/raft.py`, line 109 in `forward` during `CorrBlock` initialization

## Emergency Measures Applied ⚠️

### 1. Extreme Chunk Size Reduction
```python
# Before: 10 frames per chunk
# After: 5 frames per chunk (EMERGENCY MINIMUM)
CHUNK_SIZE = 5
OVERLAP = 1
```

**Impact:**
- ~4x more chunks (was ~62, now ~123 chunks for 493 frames)
- Processing will be MUCH slower but should complete
- More overhead from chunk boundaries

### 2. Further Resolution Reduction for 24GB GPUs
```python
# Before: 720px max dimension
# After: 540px max dimension (EMERGENCY)
```

**For your 2160x3840 video:**
- Previous attempt: 352x640 (still crashed)
- New attempt: ~304x540
- **Scale factor: 0.14x of original**

### 3. Maximum Memory Restriction
```python
# Before:
PYTORCH_CUDA_ALLOC_CONF = 'max_split_size_mb:128,garbage_collection_threshold:0.6'

# After:
PYTORCH_CUDA_ALLOC_CONF = 'max_split_size_mb:64,garbage_collection_threshold:0.5,expandable_segments:False'
PYTORCH_CUDA_ALLOC_SYNC_MEMOPS = '1'  # Force immediate memory release
```

## What This Means

### Processing Impact

| Metric | Initial | 1st Fix | EMERGENCY |
|--------|---------|---------|-----------|
| Chunk Size | 20 frames | 10 frames | **5 frames** |
| Resolution (24GB) | 1080px | 720px | **540px** |
| Your video | 608x1088 | 352x640 | **~304x540** |
| Chunks (493f) | ~25 | ~62 | **~123** |
| Memory split | 128MB | 128MB | **64MB** |

### Time Estimates

For 493-frame video:
- **Sequential (1 GPU):** ~2.5-3 hours 😱
- **Parallel (2 GPUs):** ~1.25-1.5 hours

Why so slow?
- 123 chunks vs 62 chunks (2x more)
- Lower resolution = faster per chunk, but more chunks
- Overhead from starting/stopping ProPainter 123 times

### Quality Impact

Original: 2160x3840 → Processing: 304x540 → Output: 2160x3840 (upscaled)
- **Scale down:** 0.14x (86% reduction)
- **Scale up:** 7.1x (via LANCZOS4 interpolation)
- **Visible quality loss:** Moderate to significant
  - Subtitle regions will be smoothed/blurred
  - Fine details may be lost
  - But video should still be watchable

## Why is This Happening?

ProPainter's RAFT optical flow module has memory requirements of **O(resolution² × frames)**:

```
Memory = resolution² × num_frames × coefficients

For 352x640 with 10 frames:
= (352 × 640)² × 10 × (correlation maps, feature pyramids, etc.)
= ~225,280² × 10 × ~100 bytes
≈ 50.7GB of intermediate tensors! 🔥
```

Even though you have 24GB VRAM, RAFT creates massive intermediate tensors during correlation computation.

## Alternative Solutions

If this STILL fails:

### Option 1: Pre-downscale Video
```bash
# Downscale to 720p before processing
ffmpeg -i input.mp4 -vf "scale=-1:720" input_720p.mp4
# Then process the 720p version
```

### Option 2: Use Different Tool
ProPainter may not be suitable for 4K portrait videos on 24GB GPUs. Consider:
- **LaMa** (lower quality but much faster, less VRAM)
- **E2FGVI** (newer, more efficient)
- **Manual masking** + simpler inpainting

### Option 3: Upgrade Hardware
- GPU with 40GB+ VRAM (A100, A6000)
- Or process on cloud (RunPod, Vast.ai) with bigger GPU

### Option 4: Process Regions
Instead of full video, process only subtitle regions:
1. Extract ROI (bottom 40%)
2. Process only that region
3. Composite back into original

## Testing the Emergency Fix

```bash
# The same processing command should now work
# Watch for these in logs:

[ProPainterAdapter] CHUNK_SIZE: 5 frames
[ProPainterAdapter] ProPainter processing dimensions: 304x540 (scale: 0.14x)
[ProPainterAdapter] Video too long (493 > 5). Using Sliding Window processing.
[ProPainterAdapter] Processing Chunk 1/123
```

## Monitoring

Watch GPU memory during processing:

```bash
watch -n 1 'nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv'
```

**What to expect:**
- VRAM usage: 8-12GB (was spiking to 22-24GB)
- GPU utilization: 60-80% (lower due to overhead)
- Temperature: Watch for thermal throttling

## If It STILL Fails

If you still get OOM with these emergency settings:

1. **Check GPU memory is actually clear:**
   ```bash
   nvidia-smi
   # If memory is already used, restart container
   ```

2. **Try even lower resolution:**
   Edit `propainter_adapter.py` line ~569:
   ```python
   max_dimension = 360  # Drop to 360p
   ```

3. **Try chunk size = 3:**
   Edit line ~76:
   ```python
   self.CHUNK_SIZE = 3
   ```

4. **Give up on ProPainter for this video** 😢
   It may simply be too memory-intensive for 4K portrait

## Success Criteria

✅ Processing completes without OOM  
✅ Output video is 2160x3840  
✅ Subtitles are removed  
⚠️ Quality may be degraded (expected trade-off)

---

**Status:** EMERGENCY FIX APPLIED  
**Risk Level:** 🔴 HIGH (major quality loss)  
**Recommendation:** If quality is critical, use bigger GPU or different tool  
**Date:** January 15, 2026, 10:30 AM

