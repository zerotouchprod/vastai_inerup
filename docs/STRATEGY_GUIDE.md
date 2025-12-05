# Processing Strategy Guide

## Overview

When using `--mode both`, the pipeline performs both upscaling and interpolation. You can control the order of these operations using the `--strategy` flag.

## Strategies

### 1. `interp-then-upscale` (Default, Recommended)

**Processing order:**
1. Interpolate frames at original resolution
2. Upscale interpolated frames

**Advantages:**
- ✅ **Faster** - Interpolation works on smaller frames
- ✅ **Less memory** - Upscaling processes fewer total pixels
- ✅ **Recommended for most use cases**

**Example:**
```bash
python pipeline_v2.py --mode both --strategy interp-then-upscale --input video.mp4
```

### 2. `upscale-then-interp`

**Processing order:**
1. Upscale frames to higher resolution
2. Interpolate upscaled frames

**Advantages:**
- ✅ **Potentially higher quality** - Interpolation works on higher resolution frames
- ⚠️ **Slower** - Interpolation processes larger frames
- ⚠️ **More memory** - Processing larger frame batches

**Example:**
```bash
python pipeline_v2.py --mode both --strategy upscale-then-interp --input video.mp4
```

## Configuration

You can set the strategy in three ways:

### 1. CLI Argument (Highest Priority)
```bash
python pipeline_v2.py --mode both --strategy upscale-then-interp --input video.mp4
```

### 2. Config File (config.yaml)
```yaml
mode: both
strategy: upscale-then-interp
scale: 2
interp_factor: 2.0
```

### 3. Environment Variable
```bash
export STRATEGY=upscale-then-interp
# or
export LOWRES_STRATEGY=upscale-then-interp
```

## Performance Comparison

Example with 1920x1080 video, 145 frames:

| Strategy | Processing Time | Memory Usage |
|----------|----------------|--------------|
| `interp-then-upscale` | ~3-4 minutes | ~4-6 GB |
| `upscale-then-interp` | ~5-7 minutes | ~8-12 GB |

*Times vary based on GPU/CPU performance*

## FPS Behavior

Both strategies produce the same FPS in the output:
- Original FPS × `interp_factor` = Output FPS
- Example: 24 FPS × 2.0 = 48 FPS output

The strategy only affects the *order* of operations, not the final frame rate.

## Recommendations

- **Fast processing / Limited memory**: Use `interp-then-upscale` (default)
- **Maximum quality / Abundant resources**: Use `upscale-then-interp`
- **Production pipelines**: Start with default, test both if quality is critical

## Technical Details

### interp-then-upscale
1. Extract 145 frames at 1920x1080
2. Interpolate → 290 frames at 1920x1080
3. Upscale → 290 frames at 3840x2160
4. Assemble at 48 FPS

### upscale-then-interp
1. Extract 145 frames at 1920x1080
2. Upscale → 145 frames at 3840x2160
3. Interpolate → 290 frames at 3840x2160
4. Assemble at 48 FPS

