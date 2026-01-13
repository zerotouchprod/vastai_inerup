# RIFE Interpolation - Quick Debug Guide

## 🚨 Problem: Video is Shorter Than Expected

### Quick Check (30 seconds)
```bash
# 1. Check logs for warnings
tail -100 job.log | grep -E "(WARNING|ERROR|mismatch|Missing)"

# 2. Compare input vs output
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.mp4
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 output.mp4
```

### Full Diagnosis (2 minutes)
```bash
# Run diagnostic tool
python diagnose_interp.py input.mp4 output.mp4 /tmp/job_xxx/interpolated
```

## 📊 Expected Results

### Frame Count Formula
```
output_frames = input_frames + (input_frames - 1) × (factor - 1)
```

### Common Examples
- **2x interpolation**: 192 frames → 383 frames (192 + 191×1)
- **3x interpolation**: 192 frames → 574 frames (192 + 191×2)

### Duration Should Stay Same
- Input: 192 frames @ 27 fps = 7.11s
- Output: 383 frames @ 54 fps = 7.09s ✓

## 🔍 What to Look For in Logs

### ✅ Good Signs
```
[INFO] Expected output: 383 frames (192 orig + 191 pairs × 1 mids)
[INFO] ✓ Frame count verified: 383 frames as expected
[INFO] ✓ No gaps in frame numbering (1-383)
[INFO] Duration ratio (actual/expected): 1.00x
```

### ⚠️ Warning Signs
```
[WARNING] ⚠️ Frame count mismatch! Expected 383, got 380
[WARNING] ⚠️ Duration mismatch detected! Original: 7.11s, Expected: 6.85s
[WARNING] ⚠️ Frame numbering gaps detected in first 20 frames
[ERROR] ❌ Missing frame numbers: [5, 12, 18, ...]
```

## 🛠️ Quick Fixes

### Issue 1: Missing Frames During Interpolation
**Symptom**: "Frame count mismatch! Expected X, got Y"

**Possible Causes**:
- Out of VRAM (GPU memory)
- Interpolation crashed silently
- Disk full

**Fix**:
```bash
# Check GPU memory
nvidia-smi

# Check disk space
df -h /tmp

# Try smaller batch or use CPU
python pipeline_v2.py --device cpu ...
```

### Issue 2: Wrong FPS Calculation
**Symptom**: All frames present but video is shorter

**Check**:
```bash
# Look for FPS calculation in logs
grep "INTERPOLATION FPS CALCULATION" job.log -A 10
```

**Expected**:
```
Target FPS: 27.00 × 2 = 54.00 fps
```

### Issue 3: Frame Numbering Gaps
**Symptom**: "Missing frame numbers" or "gaps detected"

**Check**:
```bash
# List first 20 frames
ls /tmp/job_xxx/interpolated/ | grep frame | head -20

# Should be sequential: frame_000001.png, frame_000002.png, ...
```

**Fix**: Usually indicates disk I/O issues or symlink failures

## 📝 Test Math Quickly

```bash
python test_frame_calculations.py --interactive

# Or calculate manually:
# output_frames = input_frames + (input_frames - 1) × (factor - 1)
# Example: 192 + (191 × 1) = 383 frames for 2x interpolation
```

## 🔧 Tools Available

1. **diagnose_interp.py** - Full video analysis
   ```bash
   python diagnose_interp.py input.mp4 output.mp4 /tmp/job_xxx/interpolated
   ```

2. **test_frame_calculations.py** - Verify math
   ```bash
   python test_frame_calculations.py
   python test_frame_calculations.py --interactive
   ```

3. **grep logs** - Find issues quickly
   ```bash
   grep -E "(mismatch|Missing|gap)" job.log
   ```

## 📞 Report Issues

When reporting, include:
1. Input video info (fps, duration, frames)
2. Expected output (frames, fps, duration)
3. Actual output (frames, fps, duration)
4. Relevant log excerpts with warnings
5. Output from diagnostic tool

Example:
```
Input: 192 frames @ 27 fps = 7.11s
Expected: 383 frames @ 54 fps = 7.09s
Actual: 380 frames @ 54 fps = 7.04s

Log warning: "Frame count mismatch! Expected 383, got 380"
Diagnostic: "Missing 3 frames during interpolation"
```

---

**Last Updated**: 2026-01-13  
**Version**: 1.0  
**Related Docs**: INTERP_ISSUE_SUMMARY.md, INTERP_DURATION_FIX.md

