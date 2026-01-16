# Watermark Removal TypeError Fix

## Issue
```
TypeError: object of type 'NoneType' has no len()
```

Error occurred at line 136 in `orchestrator.py`:
```python
self._logger.info(f"✅ Frame processing completed. Got {len(processed_frames)} processed frames")
```

## Root Cause

The orchestrator's `_process_frames()` method **did not have a handler** for the `remove-watermark` mode. This caused the method to return `None` instead of a list of processed frame paths.

### Supported Modes (Before Fix)
- ✅ `upscale` 
- ✅ `interp`
- ✅ `remove-subtitles`
- ✅ `both`
- ❌ `remove-watermark` - **MISSING!**

## Solution

Added a handler for `remove-watermark` mode in `src/application/orchestrator.py`:

### 1. Added Mode Handler in `_process_frames()`

```python
elif job.mode == "remove-watermark":
    if not self._upscaler:  # Watermark remover is passed as upscaler
        raise VideoProcessingError("Watermark remover not available")
    output_dir = workspace / "watermark_removed"
    options = {'job_id': job.job_id}
    if isinstance(job.config, dict):
        options['b2_output_key'] = job.config.get('b2_output_key')
        options['b2_bucket'] = job.config.get('b2_bucket')
    # Use watermark remover processor (passed as upscaler)
    self._logger.info(f"Starting watermark removal for {len(frame_paths)} frames")
    result = self._upscaler.process(frame_paths, output_dir, **options)
    if not result.success:
        raise VideoProcessingError(f"Watermark removal failed: {result.errors}")
    
    # Debug: list files in output directory
    all_files = list(output_dir.iterdir())
    self._logger.info(f"Watermark removal completed. Output directory contains {len(all_files)} files")
    if all_files:
        self._logger.info(f"First 5 files: {[f.name for f in all_files[:5]]}")
        # Check file extensions
        extensions = {}
        for f in all_files:
            ext = f.suffix.lower()
            extensions[ext] = extensions.get(ext, 0) + 1
        self._logger.info(f"File extensions: {extensions}")
    
    # Look for both .png and .jpg files
    processed_frames = sorted(output_dir.glob("*.png")) + sorted(output_dir.glob("*.jpg"))
    self._logger.info(f"Found {len(processed_frames)} processed frames (.png + .jpg)")
    
    if not processed_frames:
        raise VideoProcessingError(f"No processed frames found in {output_dir}")
    
    return processed_frames
```

### 2. Updated Upload Key Generation in `_generate_upload_key()`

Added watermark removal to the upload key fallback logic:

```python
# 3) fallback to timestamped key using original input basename
if job.mode == "upscale":
    return f"upscales/{base_name}-{timestamp}.mp4"
elif job.mode == "interp":
    return f"interp/{base_name}-{timestamp}.mp4"
elif job.mode == "remove-subtitles":
    return f"subtitles_removed/{base_name}-{timestamp}.mp4"
elif job.mode == "remove-watermark":
    return f"watermark_removed/{base_name}-{timestamp}.mp4"  # NEW!
else:
    return f"both/{base_name}-{timestamp}.mp4"
```

## Architecture Note

The watermark remover is passed to the orchestrator as `upscaler` parameter (similar to how subtitle remover is passed for `remove-subtitles` mode):

**CLI Setup** (`src/presentation/cli.py`):
```python
# For watermark removal mode, use watermark remover as upscaler
if config.mode == 'remove-watermark':
    upscaler = watermark_remover
```

**Orchestrator Usage**:
```python
# In remove-watermark handler:
if not self._upscaler:  # Watermark remover is passed as upscaler
    raise VideoProcessingError("Watermark remover not available")
```

This design allows reusing the existing orchestrator architecture without adding new parameters.

## Verification

### Files Modified:
- ✅ `src/application/orchestrator.py` - Added `remove-watermark` mode handler + upload key generation

### Expected Behavior After Fix:
1. ✅ Orchestrator receives `remove-watermark` job
2. ✅ Calls `_process_frames()` with mode `"remove-watermark"`
3. ✅ Handler uses `self._upscaler` (which is the watermark remover)
4. ✅ Watermark remover processes frames and returns list of paths
5. ✅ Orchestrator continues with video assembly
6. ✅ Uploads to B2 with key `watermark_removed/{job_id}.mp4`

### Testing:
```bash
python3 pipeline_v2.py \
  --mode remove-watermark \
  --input video.mp4 \
  --watermark-roi "top-right" \
  --bucket 'videos' \
  --b2-endpoint 'https://...' \
  --job '019b9e12-c91e-7095-ae1b-e93a965ca957'
```

## Related Features Already Implemented

The watermark remover wrapper already includes:

### ✅ Aspect Ratio Preservation
```python
# Validate aspect ratio preservation
self._logger.info(f"=== Aspect Ratio Validation ===")
self._logger.info(f"  Original: {orig_width}x{orig_height} (ratio: {orig_aspect:.3f})")
self._logger.info(f"  Result:   {result_width}x{result_height} (ratio: {result_aspect:.3f})")

if aspect_diff > 0.05:
    self._logger.warning(f"⚠️  Aspect ratio changed by {aspect_diff:.3f}!")
else:
    self._logger.info(f"✅ Aspect ratio preserved")
```

### ✅ Color-Aware Detection
- Detects colored watermarks (red, blue, yellow logos)
- Uses edge detection + color variance
- Configurable via `use_color=True` (default)

### ✅ VRAM-Adaptive Sampling
- RTX 3060 (6GB): 40 frames sampled
- RTX 4090 (24GB): 100 frames sampled
- Optimizes memory usage based on available VRAM

### ✅ Detailed Logging
- Frame dimensions and aspect ratio
- ROI detection statistics
- Mask coverage percentage
- Detection progress
- VRAM-based sampling strategy

## Status

✅ **FIXED** - Ready for testing on VastAI

The TypeError is now resolved. The watermark removal pipeline should work end-to-end:
1. Download video
2. Extract frames
3. Generate persistent watermark mask (color-aware, VRAM-optimized)
4. Apply ProPainter inpainting
5. Validate aspect ratio
6. Assemble video
7. Merge audio
8. Upload to B2

---

**Created:** January 8, 2026  
**Issue:** TypeError in orchestrator  
**Fix:** Added `remove-watermark` mode handler  
**Files:** `src/application/orchestrator.py`

