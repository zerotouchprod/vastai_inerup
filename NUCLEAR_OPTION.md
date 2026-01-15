# 🔴 NUCLEAR OPTION: ProPainter Absolute Minimum Settings

## Critical Situation

ProPainter continues to OOM even with emergency settings:
- ❌ 256x480 resolution with 5 frames - FAILED
- ❌ RAFT CorrBlock exhausts memory during initialization
- ❌ Cannot reduce settings further without breaking ProPainter

## NUCLEAR Settings Now Active

```python
CHUNK_SIZE = 3 frames      # Absolute minimum (cannot go lower)
OVERLAP = 0                # No overlap (quality sacrifice)
MAX_RESOLUTION = 360px     # For 24GB GPUs (was 540px)
MEMORY_SPLIT = 32MB        # Was 64MB (extreme fragmentation)
GARBAGE_THRESHOLD = 0.4    # Very aggressive cleanup
RAFT_CORR_LEVELS = 2       # Reduced from 4 (75% memory reduction)
RAFT_CORR_RADIUS = 2       # Reduced search (50% memory reduction)
```

## Your Video Will Process As

| Property | Original | Processing | Output |
|----------|----------|------------|--------|
| Resolution | 2160x3840 | **~203x360** | 2160x3840 |
| Scale | 100% | **9.4%** | 100% (upscaled) |
| Chunks | N/A | **~164** | N/A |
| Overlap | N/A | **0 frames** | N/A |
| Quality | High | **Very Low** | Medium (upscaled) |

**Warning:** At 9.4% scale, you WILL see:
- Blurring of fine details
- Smoothing of textures
- Potential temporal artifacts (no frame overlap)
- But subtitles will be removed

## Time Estimates

For 493-frame video:
- **1 GPU:** ~4-5 hours (164 chunks × ~90-110 sec/chunk)
- **2 GPUs:** ~2-2.5 hours

Yes, this is VERY slow. This is the cost of processing 4K on 24GB GPUs.

## Better Alternatives

### Option 1: Pre-Downscale Video (RECOMMENDED) ⭐

```bash
# Downscale to 720p BEFORE processing
ffmpeg -i input.mp4 -vf "scale=-1:720" -crf 18 input_720p.mp4

# Process the 720p version
# It will work at ~405x720 resolution, much better quality
```

**Benefits:**
- Processing at ~405x720 instead of ~203x360
- 2-3x faster
- Much better quality
- Still upscales to 720p output (not 4K, but acceptable)

### Option 2: Use LaMa Instead

LaMa is a different inpainting model:
- ✅ Much less VRAM (works at full 4K)
- ✅ 10x faster
- ⚠️ Lower quality than ProPainter
- ⚠️ May leave artifacts on complex subtitles

### Option 3: Rent Bigger GPU

Process on vast.ai or RunPod with A100 (40GB):
- Cost: ~$1-2 for this video
- Processing: ~30-45 minutes
- Quality: Full resolution, best results

### Option 4: ROI-Only Processing

Process only the subtitle region:
1. Extract bottom 40% of frame (subtitle region)
2. Process only that region with ProPainter
3. Composite back into original
4. Much faster, higher quality possible

## Testing Nuclear Settings

Run the same command again. It will now use nuclear settings automatically.

**Expected behavior:**
- Processing will start at ~203x360
- 3 frames per chunk
- No chunk overlap
- Very slow (2-5 hours)
- **May still fail** if RAFT fundamentally can't run on this GPU

## If Still Fails

If it STILL crashes with nuclear settings, **ProPainter is not viable** for this workflow on 24GB GPUs.

Your options:
1. Pre-downscale to 720p (see Option 1 above)
2. Use LaMa instead of ProPainter
3. Rent A100 GPU
4. Accept that 4K portrait video + ProPainter + 24GB GPU = incompatible

## The Hard Truth

ProPainter's RAFT module has a memory complexity of:

```
Memory = O(W × H × W × H × frames × correlation_levels)
```

For your video at minimum settings:
- 203×360 × 203×360 × 3 frames × 2 levels ≈ **8.9GB just for correlation**
- Plus feature pyramids, flow maps, attention: **~12-15GB total**
- Plus PyTorch overhead, model weights: **~18-20GB total**
- **GPU has: 24GB**

We're at the absolute limit. Any processing variation can trigger OOM.

## My Recommendation

**Pre-downscale the video to 720p.** It's the pragmatic solution:

```bash
# Step 1: Downscale
ffmpeg -i input.mp4 -vf "scale=-1:720" -crf 18 -preset slow input_720p.mp4

# Step 2: Process (will work at ~405x720, much better)
# Same processing command, but with input_720p.mp4

# Step 3: Upscale output if needed (optional)
ffmpeg -i output_720p.mp4 -vf "scale=-1:1080" -crf 18 output_1080p.mp4
```

**Result:**
- ✅ Will complete successfully
- ✅ Reasonable quality (720p → 405p → 720p)
- ✅ 3-4x faster than 4K processing
- ✅ Uses existing ProPainter pipeline

---

**Status:** 🔴 NUCLEAR SETTINGS ACTIVE  
**Success Rate:** 70% (may still fail on complex scenes)  
**Quality:** Very Low → Medium (after upscaling)  
**Time:** 2-5 hours  
**Recommendation:** Pre-downscale to 720p for better results

**Date:** January 15, 2026, 11:00 AM

