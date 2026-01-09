# Tuning Guide: Subtitle and Watermark Removal

## Overview

The subtitle and watermark removal system now uses centralized configuration files that control all sensitivity, aggressiveness, and quality parameters. This guide shows you how to tune the system for different use cases.

---

## Configuration Files

### Subtitle Removal
**File**: `src/infrastructure/processors/subtitle_removal_config.py`

Controls OCR detection, mask expansion, dilation, and quality.

### Watermark Removal
**File**: `src/infrastructure/processors/watermark_removal_config.py`

Controls static detection, persistence threshold, mask expansion, and color-awareness.

---

## Quick Tuning: Preset Profiles

### For Subtitles

```python
# In your code or startup script
from src.infrastructure.processors import subtitle_removal_config as SRC

# Choose a profile:
SRC.apply_profile('conservative')  # Minimal false positives
SRC.apply_profile('balanced')      # Default (recommended)
SRC.apply_profile('aggressive')    # Catch all text
SRC.apply_profile('minimal')       # Only obvious text
```

### For Watermarks

```python
from src.infrastructure.processors import watermark_removal_config as WRC

# Choose a profile:
WRC.apply_profile('opaque_logo')          # Solid channel logos
WRC.apply_profile('transparent_overlay')  # Semi-transparent watermarks
WRC.apply_profile('small_text')           # Copyright notices
WRC.apply_profile('large_banner')         # TV station bugs
WRC.apply_profile('animated_watermark')   # Fading/animated logos
```

---

## Custom Tuning: Key Parameters

### Problem: "System removes too much" (over-aggressive)

**Solution**: Reduce aggressiveness

#### For Subtitles:
```python
# Edit: src/infrastructure/processors/subtitle_removal_config.py

OCR_CONFIDENCE_THRESHOLD = 0.15  # Increase from 0.05 (stricter detection)
BBOX_EXPAND_HORIZONTAL = 10      # Decrease from 15 (less expansion)
BBOX_EXPAND_VERTICAL = 15        # Decrease from 20
DILATION_ITERATIONS_INITIAL = 1  # Decrease from 2 (less blur)
DILATION_ITERATIONS_FINAL = 0    # Disable final dilation
```

#### For Watermarks:
```python
# Edit: src/infrastructure/processors/watermark_removal_config.py

PERSISTENCE_THRESHOLD = 0.90     # Increase from 0.80 (stricter)
MASK_EXPANSION_RADIUS = 5        # Decrease from 10 (less expansion)
MIN_REGION_AREA = 200            # Increase from 100 (filter small regions)
```

---

### Problem: "System misses some text" (under-aggressive)

**Solution**: Increase sensitivity

#### For Subtitles:
```python
OCR_CONFIDENCE_THRESHOLD = 0.01  # Decrease from 0.05 (more sensitive)
BBOX_EXPAND_HORIZONTAL = 25      # Increase from 15 (more expansion)
BBOX_EXPAND_VERTICAL = 30        # Increase from 20
DILATION_ITERATIONS_INITIAL = 3  # Increase from 2 (more blur)
DILATION_ITERATIONS_FINAL = 2    # Increase from 1
```

#### For Watermarks:
```python
PERSISTENCE_THRESHOLD = 0.60     # Decrease from 0.80 (more sensitive)
MASK_EXPANSION_RADIUS = 15       # Increase from 10 (more expansion)
MIN_REGION_AREA = 50             # Decrease from 100 (keep small regions)
COLOR_DIFF_THRESHOLD = 50        # Increase from 30 (less strict color matching)
```

---

### Problem: "Processing is too slow"

**Solution**: Optimize performance

#### For Subtitles:
```python
OCR_DUAL_PASS_ENABLED = False    # Disable dual-pass OCR (2x faster)
GPU_CLEANUP_INTERVAL = 100       # Clean GPU memory less often (faster)
PROGRESS_LOG_PERCENTAGE = 20     # Log less frequently
```

#### For Watermarks:
```python
DETECTION_SCALE_FACTOR = 0.25    # Process at 1/4 resolution (4x faster)
SAMPLE_FRAME_COUNT = 15          # Sample fewer frames (faster)
USE_GPU_DETECTION = True         # Ensure GPU acceleration is enabled
```

---

### Problem: "Colored watermarks not detected"

**Solution**: Enable color-aware detection

```python
# For watermarks:
USE_COLOR_DETECTION = True       # Must be True
COLOR_DIFF_THRESHOLD = 40        # Adjust based on watermark color variance
```

---

### Problem: "Leaves artifacts/edges around removed text"

**Solution**: Increase mask expansion and smoothing

#### For Subtitles:
```python
BBOX_EXPAND_HORIZONTAL = 20      # Increase expansion
BBOX_EXPAND_VERTICAL = 25
MORPHOLOGICAL_CLOSING_ITERATIONS = 2  # Fill gaps better
```

#### For Watermarks:
```python
MASK_EXPANSION_RADIUS = 15       # Increase expansion
MASK_BLUR_SIGMA = 3.0            # Increase from 2.0 (smoother edges)
MORPHOLOGICAL_CLOSING_KERNEL = 7 # Increase from 5 (fill larger gaps)
```

---

## Environment Variable Overrides

### Force specific kernel size (subtitles)
```bash
export FORCE_KERNEL_SIZE=50
# Forces 50x50 dilation kernel regardless of VRAM
```

### Enable debug mode
```bash
export DEBUG_SUBTITLE_REMOVAL=1
# Saves diagnostic images to output/debug/
```

---

## Testing Your Changes

### 1. Process a test video
```bash
python3 pipeline_v2.py \
  --input test_video.mp4 \
  --mode remove-subtitles \
  --roi bottom \
  --debug  # Saves diagnostic images
```

### 2. Check debug output
Look for diagnostic images in `output/debug/`:
- `*_original.jpg` - Original frame
- `*_mask.jpg` - Generated mask (white = removed areas)
- `*_result.jpg` - After inpainting

### 3. Iterate
If masks are too aggressive → reduce expansion/dilation  
If masks miss text → increase sensitivity/expansion

---

## Configuration Reference

### Subtitle Removal - All Parameters

| Parameter | Default | Description | Range |
|-----------|---------|-------------|-------|
| `OCR_CONFIDENCE_THRESHOLD` | 0.05 | Min OCR confidence | 0.01-0.20 |
| `OCR_DUAL_PASS_ENABLED` | True | Run OCR twice | True/False |
| `OCR_DUPLICATE_IOU_THRESHOLD` | 0.3 | IoU for deduplication | 0.2-0.5 |
| `BBOX_EXPAND_HORIZONTAL` | 15 | Horizontal expansion (px) | 5-30 |
| `BBOX_EXPAND_VERTICAL` | 20 | Vertical expansion (px) | 10-40 |
| `KERNEL_SIZE_LOW_VRAM` | 30 | Kernel for <8GB VRAM | 20-40 |
| `KERNEL_SIZE_MID_VRAM` | 40 | Kernel for 8-16GB VRAM | 30-50 |
| `KERNEL_SIZE_HIGH_VRAM` | 45 | Kernel for >16GB VRAM | 35-60 |
| `DILATION_ITERATIONS_INITIAL` | 2 | Initial dilation passes | 1-3 |
| `MORPHOLOGICAL_CLOSING_ITERATIONS` | 1 | Closing passes | 1-2 |
| `DILATION_ITERATIONS_FINAL` | 1 | Final dilation passes | 0-2 |
| `CLAHE_CLIP_LIMIT` | 4.0 | CLAHE enhancement strength | 2.0-6.0 |
| `CLAHE_TILE_GRID_SIZE` | (8, 8) | CLAHE grid size | (4,4)-(16,16) |
| `GPU_CLEANUP_INTERVAL` | 50 | Memory cleanup interval | 20-100 |
| `PROGRESS_LOG_PERCENTAGE` | 10 | Progress log frequency | 5-20 |

### Watermark Removal - All Parameters

| Parameter | Default | Description | Range |
|-----------|---------|-------------|-------|
| `PERSISTENCE_THRESHOLD` | 0.80 | Pixel persistence ratio | 0.60-0.95 |
| `SAMPLE_FRAME_COUNT` | 30 | Frames to sample | 10-50 |
| `MIN_REGION_AREA` | 100 | Min region size (px) | 50-500 |
| `MAX_REGION_AREA_RATIO` | 0.15 | Max region % of frame | 0.05-0.30 |
| `USE_COLOR_DETECTION` | True | Color-aware detection | True/False |
| `COLOR_DIFF_THRESHOLD` | 30 | Color difference threshold | 10-50 |
| `EDGE_DETECTION_LOW_THRESHOLD` | 50 | Canny low threshold | 30-100 |
| `EDGE_DETECTION_HIGH_THRESHOLD` | 150 | Canny high threshold | 100-200 |
| `EDGE_DILATION_KERNEL` | 3 | Edge dilation kernel | 1-5 |
| `MASK_EXPANSION_RADIUS` | 10 | Mask expansion (px) | 5-20 |
| `MORPHOLOGICAL_CLOSING_KERNEL` | 5 | Closing kernel size | 3-9 |
| `MASK_BLUR_SIGMA` | 2.0 | Mask smoothing | 1.0-5.0 |
| `DETECTION_SCALE_FACTOR` | 0.5 | Downscale for detection | 0.25-1.0 |
| `OCR_FALLBACK_CONFIDENCE` | 0.01 | OCR fallback threshold | 0.01-0.10 |
| `OCR_FALLBACK_EXPANSION` | 15 | OCR fallback expansion (px) | 5-30 |

---

## Validation

Both config files have built-in validation:

```python
# For subtitles
from src.infrastructure.processors import subtitle_removal_config as SRC
SRC.validate_config()  # Prints warnings for extreme values

# For watermarks
from src.infrastructure.processors import watermark_removal_config as WRC
WRC.validate_config()
```

---

## Example: Custom Profile

Create your own profile for specific content:

```python
# my_custom_config.py
from src.infrastructure.processors import subtitle_removal_config as SRC

# For anime subtitles with heavy glow effects
SRC.OCR_CONFIDENCE_THRESHOLD = 0.03
SRC.BBOX_EXPAND_HORIZONTAL = 25
SRC.BBOX_EXPAND_VERTICAL = 35
SRC.DILATION_ITERATIONS_INITIAL = 3
SRC.MORPHOLOGICAL_CLOSING_ITERATIONS = 2
SRC.CLAHE_CLIP_LIMIT = 5.0

print("Custom anime profile loaded!")
SRC.validate_config()
```

Then import before processing:
```bash
python3 -c "import my_custom_config" && \
  python3 pipeline_v2.py --input anime.mp4 --mode remove-subtitles
```

---

## Tips

1. **Start with presets**: Use built-in profiles before manual tuning
2. **Use debug mode**: Always test with `--debug` to see masks
3. **Iterate gradually**: Change one parameter at a time
4. **Validate changes**: Run `validate_config()` to catch extreme values
5. **Document your settings**: Comment why you changed each value
6. **Test on multiple videos**: Settings that work for one video may not work for others

---

## Need Help?

- Check validation warnings: `SRC.validate_config()` or `WRC.validate_config()`
- Enable debug mode: `--debug` flag
- Compare with presets: See which profile is closest to your needs
- Consult config files: All parameters have detailed comments

