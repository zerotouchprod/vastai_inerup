# FPS Calculation Fix for Interpolation Mode

## Problem (CORRECTED)

In `interp` mode, after 2x interpolation:
- Original: 145 frames @ 24 fps = 6 seconds
- After interpolation: 289 frames @ **24 fps** = 12 seconds ❌

**Result:** Video duration doubled, creating unwanted slow-motion effect. User wanted smoother motion at **same speed**, not slow-motion.

## Root Cause

The orchestrator was keeping the original FPS instead of multiplying it by the interpolation factor:
```python
# WRONG:
target_fps = original_fps  # 24 fps
# This makes video 2x longer (slow-motion)
```

## Solution

Changed the FPS calculation for `interp` mode to **MULTIPLY FPS by interpolation factor**:

```python
elif job.mode == 'interp':
    # For interpolation: MULTIPLY the FPS by the interpolation factor
    # More frames at higher FPS = same duration, smoother motion
    # Example: 145→289 frames @ 48 fps (24*2) → stays 6s but smoother
    interp_factor = int(job.interp_factor) if hasattr(job, 'interp_factor') else 2
    target_fps = original_fps * interp_factor
```

## Result (After Fix)

- Original: 145 frames @ 24 fps = 6 seconds
- After 2x interpolation: 289 frames @ **48 fps** (24 * 2) = **6 seconds** ✓

**Result:** Video duration stays the same, motion becomes smoother (higher framerate).

## Technical Details

### Interpolation Factor Behavior (CORRECTED)
- **Factor = 2:** FPS doubles (24 → 48 fps), duration stays same
- **Factor = 3:** FPS triples (24 → 72 fps), duration stays same  
- **Factor = 4:** FPS quadruples (24 → 96 fps), duration stays same

### Formula
```
new_fps = original_fps * interpolation_factor
new_duration = total_frames / new_fps
            = 289 / (24 * 2)
            = 289 / 48
            = 6.02 seconds (same as original)
```

## Files Changed
- `src/application/orchestrator.py` - Fixed FPS calculation in `_process_frames()` method

## Date
December 5, 2025

