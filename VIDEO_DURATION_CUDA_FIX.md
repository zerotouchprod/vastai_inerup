# Video Duration & CUDA Compatibility Fixes

## Date: December 5, 2024

## Issues Fixed

### 1. CUDA Compatibility Issue (RTX 5060 Ti)

**Problem**: RTX 5060 Ti has compute capability sm_120, but PyTorch 2.2.2+cu121 only supports up to sm_90.

**Error**:
```
CUDA error: no kernel image is available for execution on the device
```

**Solution**: Added automatic CUDA compatibility check with CPU fallback:
- `_check_cuda_compatibility()` method in `RIFENative` class
- Tries a test CUDA operation before loading model
- Automatically falls back to CPU if CUDA is incompatible
- Logs warnings so user knows processing will be slower

**Files Changed**:
- `src/infrastructure/processors/rife/native.py`: Added compatibility check

### 2. Video Duration Issue (Interpolation Mode)

**Problem**: After interpolation, output videos are half the expected duration:
- Input: 6 seconds @ 24fps (145 frames)
- After interpolation: 289 frames
- Expected output: 6 seconds @ 48fps  
- Actual output: 3 seconds @ 24fps (WRONG!)

**Root Cause**: Unknown - need more debug logs to identify

**Investigation Steps**:
1. Added comprehensive ffmpeg logging to see actual encoding parameters
2. Logs now show:
   - Frame count and expected duration calculation
   - Actual ffmpeg command with all parameters
   - FFmpeg stdout/stderr output
   - Actual video FPS and duration after encoding
   - Duration ratio (actual/expected)

**Files Changed**:
- `src/infrastructure/media/ffmpeg.py`: Added assembly debug logging

## Testing

Run this on remote server to test the CUDA fallback:
```bash
python test_cuda_fallback.py
```

Run a full interpolation test to see duration logs:
```bash
python ssh_run.py pipeline_v2.py --mode interp --input https://f004.backblazeb2.com/file/noxfvr-videos/input/c1/qad.mp4 --job testfps
```

Look for these logs:
```
[ASSEMBLY DEBUG] Frames dir: ...
[ASSEMBLY DEBUG] Frame count: 289
[ASSEMBLY DEBUG] Target FPS: 48.0
[ASSEMBLY DEBUG] Expected duration: 6.02s
[ASSEMBLY DEBUG] FFmpeg command: ...
[ASSEMBLY DEBUG] FFmpeg stderr: ...
[ASSEMBLY DEBUG] Actual FPS: ...
[ASSEMBLY DEBUG] Actual duration: ...
[ASSEMBLY DEBUG] Duration ratio: ...
```

If duration ratio is ~0.5x, ffmpeg is encoding at wrong FPS (probably 24fps instead of 48fps).

## Next Steps

1. Test CUDA fallback on RTX 5060 Ti (should use CPU)
2. Run interpolation test and collect ffmpeg logs
3. Analyze why ffmpeg outputs 24fps video instead of 48fps
4. Possible fixes if ffmpeg ignores -r parameter:
   - Use -filter:v "setpts=0.5*PTS" to speed up by 2x
   - Use -vsync vfr instead of cfr
   - Explicitly set time_base
   - Use concat demuxer instead of image2 for better frame rate control

## Files Modified

1. `src/infrastructure/media/ffmpeg.py`
   - Added comprehensive assembly debug logging
   - Logs ffmpeg command, output, actual FPS/duration

2. `src/infrastructure/processors/rife/native.py`
   - Added `_check_cuda_compatibility()` method
   - Automatic CPU fallback for incompatible GPUs
   - Logs warnings when using CPU

3. `test_cuda_fallback.py` (new)
   - Test script to verify CUDA compatibility detection

## Related Issues

- Duration issue affects all interpolation modes (interp, both)
- CUDA issue affects any GPU with compute capability > sm_90
- Both issues block production use of native processors

