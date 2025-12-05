# FPS Calculation Fix for Interpolation Mode

## Problem

In `interp` mode, after 2x interpolation:
- Original: 145 frames @ 24 fps = 6 seconds
- After interpolation: 289 frames @ **48 fps** = 6 seconds ❌

**Result:** Video duration stayed the same, frames were just smoother but compressed into the same timeframe. Video appeared to play at normal speed.

## Root Cause

The orchestrator was calculating target FPS by dividing processed frames by original duration:
```python
target_fps = processed_frame_count / original_duration
target_fps = 289 / 6.04 = 47.83 fps
```

This maintained the same video duration but defeated the purpose of interpolation.

## Solution

Changed the FPS calculation for `interp` mode to **KEEP the original FPS**:

```python
elif job.mode == 'interp':
    # For interpolation: KEEP the original FPS
    # More frames at same FPS = longer, smoother video
    # Example: 145→289 frames @ 24 fps → 6s becomes 12s (2x slower/smoother)
    target_fps = original_fps
```

## Result (After Fix)

- Original: 145 frames @ 24 fps = 6 seconds
- After 2x interpolation: 289 frames @ **24 fps** = **12 seconds** ✓

**Result:** Video duration doubles, creating smooth slow-motion effect.

## Technical Details

### Interpolation Factor Behavior
- **Factor = 2:** Video becomes 2x longer (slow-motion @ 0.5x speed)
- **Factor = 3:** Video becomes 3x longer (slow-motion @ 0.33x speed)
- **Factor = 4:** Video becomes 4x longer (slow-motion @ 0.25x speed)

### Formula
```
new_duration = (original_frames * factor - (factor - 1)) / original_fps
            = 289 / 24 
            = 12.04 seconds
```

## Files Changed
- `src/application/orchestrator.py` - Fixed FPS calculation in `_process_frames()` method

## Date
December 5, 2025

