# RIFE Interpolation Duration Issue - Analysis & Fix

## Problem
Interpolated videos are shorter than original videos (e.g., 8 seconds → 7 seconds) and sometimes have playback issues (freezing).

## Root Causes Identified

### 1. **Frame Count Calculation Error**
In `native.py`, the `_calculate_mids_per_pair()` method used `int(self.factor) - 1` which loses precision:
- For factor=2.0: calculates 1 mid per pair ✓
- For factor=3.0: calculates 2 mids per pair ✓
- **But**: using `int()` directly could truncate float values incorrectly

**Fix**: Changed to `int(round(self.factor)) - 1` for proper rounding.

### 2. **Missing Frame Verification**
The original code had no verification that:
- All expected frames were generated
- Frame numbering was sequential without gaps
- Output frame count matched mathematical expectation

**Fix**: Added comprehensive logging:
- Expected output frame calculation: `input_frames + (pairs × mids_per_pair)`
- Frame count verification after interpolation
- Sequential frame numbering check
- Gap detection in frame sequence

### 3. **FPS Calculation Mismatch**
The orchestrator multiplies `original_fps * interp_factor` but doesn't verify:
- The actual number of frames generated matches expectation
- The resulting duration will match original video

**Fix**: Added detailed logging showing:
- Input frames and FPS
- Interpolation factor
- Output frames
- Target FPS calculation
- Expected vs actual duration

### 4. **FFmpeg Assembly Issues**
The assembly command uses:
```bash
-framerate {fps}  # Input framerate
-r {fps}          # Output framerate
-vsync cfr        # Constant frame rate
```

**Potential Issues**:
- If frame numbering has gaps (e.g., frame_000001.png, frame_000003.png), FFmpeg may skip frames
- If frame count doesn't match FPS×duration, video will be shorter

**Fix**: Added frame sequence validation before assembly.

## Changes Made

### File: `src/infrastructure/processors/rife/native.py`

1. **Improved `_calculate_mids_per_pair()`**:
   ```python
   mids = max(1, int(round(self.factor)) - 1)
   ```

2. **Added debug logging in `process_frames()`**:
   - Log expected output frame count
   - Log frame details for first pair
   - Verify actual vs expected frame count
   - Check for gaps in frame numbering
   - Error if frames are missing

3. **Enhanced progress reporting**:
   - Show frame counter for each generated frame
   - Warn if interpolated frame count doesn't match expectation

### File: `src/application/orchestrator.py`

1. **Enhanced interpolation validation**:
   - Log input frame count before interpolation
   - Calculate expected output frame count
   - Verify actual output matches expectation
   - Warn if mismatch detected

2. **Improved FPS calculation logging**:
   - Show detailed calculation for interp mode
   - Verify frame count matches mathematical expectation
   - Calculate expected duration and compare with original
   - Warn if duration discrepancy > 0.5s

### File: `src/infrastructure/media/ffmpeg.py`

1. **Enhanced assembly validation**:
   - Check frame numbering is sequential
   - Detect gaps in frame numbers
   - Log first/last frame names
   - Verify frame count before assembly

## Diagnostic Tool

Created `diagnose_interp.py` to analyze:
- Input video properties (FPS, duration, frame count)
- Output video properties
- Interpolated frames directory
- Frame sequence gaps
- Expected vs actual frame counts

**Usage**:
```bash
python diagnose_interp.py input.mp4 output.mp4 /tmp/job_xxx/interpolated
```

## Expected Behavior After Fix

### For 2x Interpolation (factor=2):
- Input: 192 frames @ 27 fps = 7.1s
- Interpolation: 192 + (191 pairs × 1 mid) = **383 frames**
- Output: 383 frames @ 54 fps = **7.1s** ✓

### For 3x Interpolation (factor=3):
- Input: 192 frames @ 27 fps = 7.1s
- Interpolation: 192 + (191 pairs × 2 mids) = **574 frames**
- Output: 574 frames @ 81 fps = **7.1s** ✓

## How to Test

1. **Check logs for warnings**:
   ```bash
   grep -E "(Frame count mismatch|Duration mismatch|Missing frame)" job.log
   ```

2. **Run diagnostic tool**:
   ```bash
   python diagnose_interp.py input.mp4 output.mp4 /tmp/job_xxx/interpolated
   ```

3. **Verify frame sequence**:
   ```bash
   ls -1 /tmp/job_xxx/interpolated/frame_*.png | wc -l
   ```

4. **Check for gaps**:
   ```bash
   # Should be sequential: 1, 2, 3, 4, ...
   ls /tmp/job_xxx/interpolated/ | grep frame | head -20
   ```

## Common Issues to Watch

1. **Frame numbering gaps**: If symlinks fail, original frames might not be copied correctly
2. **OOM (Out of Memory)**: Large videos may run out of VRAM during interpolation
3. **FFmpeg encoder issues**: h264_nvenc might fail on some GPUs, falling back to libx264
4. **CFR (Constant Frame Rate) issues**: If timestamps are irregular, video players may stutter

## Next Steps

1. Run interpolation with new logging
2. Check for warnings in logs
3. Use diagnostic tool to verify frame counts
4. If issues persist, check:
   - GPU VRAM usage (may need to process in smaller batches)
   - FFmpeg stderr output for encoding errors
   - Frame file sizes (corrupted frames will be smaller)

## Warning Messages to Watch

- `⚠️ Frame count mismatch!` - Interpolation didn't generate expected frames
- `⚠️ Duration mismatch detected!` - Output video will be shorter/longer than original
- `⚠️ Frame numbering gaps detected` - FFmpeg may skip frames during assembly
- `⚠️ Duration mismatch! Expected X but got Y` - Assembly resulted in wrong duration

These warnings will help identify exactly where the problem occurs.

