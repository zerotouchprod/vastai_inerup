# FPS Fix Summary - December 5, 2025

## Issue
Video interpolation (2x) was outputting at 24 fps instead of 48 fps, making videos 2x longer (slow-motion) instead of smoother at the same duration.

**Status:** FIX APPLIED - logs show correct behavior (48 fps), but user reports video is 2x shorter (3s instead of 6s). Investigating actual video file properties vs. logged values.

## Root Cause
The orchestrator was keeping the original FPS for interpolated videos instead of multiplying by the interpolation factor.

**Wrong behavior:**
- Input: 145 frames @ 24 fps = 6 seconds
- After 2x interpolation: 289 frames @ 24 fps = 12 seconds (slow-motion ❌)

**Correct behavior:**
- Input: 145 frames @ 24 fps = 6 seconds  
- After 2x interpolation: 289 frames @ 48 fps = 6 seconds (smooth ✓)

## Solution
Modified `src/application/orchestrator.py` to multiply original FPS by interpolation factor in `interp` mode:

```python
elif job.mode == 'interp':
    interp_factor = int(job.interp_factor) if hasattr(job, 'interp_factor') else 2
    target_fps = original_fps * interp_factor  # 24 * 2 = 48 fps
```

## Files Changed
1. `src/application/orchestrator.py` - Fixed FPS calculation logic
2. `FPS_FIX_INTERP_MODE.md` - Updated documentation
3. `test_fps_calculation.py` - Updated test to reflect correct behavior

## Expected Behavior After Fix
- **Interp mode:** FPS multiplied by factor (24 → 48 fps for 2x), duration stays same
- **Both mode:** FPS calculated to maintain original duration
- **Upscale mode:** FPS unchanged (same frame count)

## Testing
Run the test to verify:
```bash
python test_fps_calculation.py
```

Expected output for interp mode:
```
2. INTERP mode (145 frames @ 24fps -> 289 frames, 2x interpolation)
   Original: 145 frames @ 24.0 fps = 6.04s
   Processed: 289 frames
   Target FPS: 48.00 (interp mode (FPS * 2x factor))
   Output: 289 frames @ 48.00 fps = 6.02s
   ✓ Duration preserved: True
```

## Impact
- Interpolation now produces smoother video at the **same speed** (not slow-motion)
- Video duration remains unchanged
- Framerate properly doubled (or tripled/quadrupled for higher factors)

## Investigation: User Reports Video is 2x Shorter

**User Report:** Video duration is 3 seconds instead of 6 seconds (2x shorter)

**Logs Show:** `289 frames @ 48.0 fps = 6.02s (original duration)`

**Possible Causes:**
1. **FFmpeg assembly issue** - Logs show correct FPS calculation, but ffmpeg might not be applying it correctly
2. **Frame count mismatch** - Maybe only 144 frames (interpolated only) instead of 289 (original + interpolated)
3. **Video player interpretation** - Player might be reading wrong metadata
4. **Caching issue** - Browser/player showing old version

**Next Steps:**
1. Run `python verify_interp_video.py` to check actual video file properties
2. Compare frame count in output directory: should be 289 files
3. Check ffmpeg assembly command in logs for any issues
4. Verify input video is actually 6 seconds (not 3 seconds)

