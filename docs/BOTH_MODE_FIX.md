# Fix: Both Mode Processing (Interpolation + Upscale)

## Problem
When using `--mode both`, the pipeline was only performing interpolation and not upscaling. The output video had interpolated frames but was not upscaled.

## Root Cause
The bash wrapper scripts (`run_rife_pytorch.sh` and `run_realesrgan_pytorch.sh`) were automatically uploading intermediate results to B2 storage and marking the processing as complete (`VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY`), even though it was just an intermediate stage in a multi-step pipeline.

## Solution
Added `_intermediate_stage` flag support:

### 1. Modified Orchestrator (`src/application/orchestrator.py`)
- In `both` mode, set `_intermediate_stage=True` for both processing steps
- This tells the wrapper scripts NOT to upload intermediate results
- The orchestrator handles the final upload after all processing is complete

### 2. Modified RIFE Wrapper (`src/infrastructure/processors/rife/pytorch_wrapper.py`)
- Check for `_intermediate_stage` flag in options
- If true, set `AUTO_UPLOAD_B2=0` environment variable
- This disables automatic B2 upload in the bash script

### 3. Modified Real-ESRGAN Wrapper (`src/infrastructure/processors/realesrgan/pytorch_wrapper.py`)
- Same logic as RIFE wrapper
- Disable AUTO_UPLOAD_B2 when in intermediate stage

### 4. Fixed CLI Arguments (`src/presentation/cli.py`)
- Fixed `--strategy` argument choices to match model values:
  - `interp-then-upscale` (default)
  - `upscale-then-interp`

### 5. Added Validation (`src/domain/models.py`)
- Added validation for `strategy` field in `ProcessingJob`
- Ensures only valid strategy values are accepted

## Processing Flow in "both" Mode

### Strategy: interp-then-upscale (default)
1. **Interpolation** (intermediate stage - no upload)
   - Input: original frames
   - Output: interpolated frames in temp directory
   - AUTO_UPLOAD_B2=0 (no upload)

2. **Upscaling** (intermediate stage - no upload)
   - Input: interpolated frames
   - Output: upscaled frames in temp directory
   - AUTO_UPLOAD_B2=0 (no upload)

3. **Assembly & Upload** (final stage)
   - Input: upscaled frames
   - Orchestrator assembles video with correct FPS
   - Orchestrator uploads final video to B2

### Strategy: upscale-then-interp
1. **Upscaling** (intermediate stage - no upload)
   - Input: original frames
   - Output: upscaled frames
   - AUTO_UPLOAD_B2=0

2. **Interpolation** (intermediate stage - no upload)
   - Input: upscaled frames
   - Output: interpolated frames
   - AUTO_UPLOAD_B2=0

3. **Assembly & Upload** (final stage)
   - Orchestrator assembles and uploads

## Testing
Test with:
```bash
python pipeline_v2.py --mode both --input <video-url> --job testboth
python pipeline_v2.py --mode both --input <video-url> --strategy upscale-then-interp --job testboth2
```

Expected result:
- Both interpolation and upscaling are performed
- Only final result is uploaded to B2
- No intermediate uploads
- Correct FPS in final video

