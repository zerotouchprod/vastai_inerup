# ROI Format Documentation

## Format: x,y,w,h

ROI (Region of Interest) uses normalized coordinates in the format `x,y,w,h`:

- **x**: Horizontal position (0.0 = left edge, 1.0 = right edge)
- **y**: Vertical position (0.0 = top edge, 1.0 = bottom edge)  
- **w**: Width as fraction of frame width (0.0 to 1.0)
- **h**: Height as fraction of frame height (0.0 to 1.0)

## Examples

### Example 1: Bottom Half (for subtitles)
```bash
--roi '0.0,0.5,1.0,0.5'
```
- x=0.0 (start at left edge)
- y=0.5 (start at 50% down from top)
- w=1.0 (full width)
- h=0.5 (50% height)
- **Result**: Covers bottom 50% of frame (from 50% to 100%)

### Example 2: Lower 40% (slightly above bottom)
```bash
--roi '0.0,0.5,1.0,0.4'
```
- x=0.0 (start at left edge)
- y=0.5 (start at 50% down)
- w=1.0 (full width)
- h=0.4 (40% height)
- **Result**: Covers region from 50% to 90% of frame height

### Example 3: Top-Right Corner (for watermarks)
```bash
--roi '0.8,0.0,0.2,0.2'
```
- x=0.8 (start at 80% from left)
- y=0.0 (start at top)
- w=0.2 (20% width)
- h=0.2 (20% height)
- **Result**: Small box in top-right corner

### Example 4: Vertical Strip (side watermark)
```bash
--roi '0.85,0.0,0.15,1.0'
```
- x=0.85 (start at 85% from left)
- y=0.0 (start at top)
- w=0.15 (15% width)
- h=1.0 (full height)
- **Result**: Narrow vertical strip on right side

## Presets

Instead of coordinates, you can use presets:

### Subtitle Presets
- `bottom` - Bottom 60% of screen (default for subtitles)
- `top` - Top 30% of screen
- `full` - Entire frame (no filtering)

### Watermark Presets  
- `top-left` - Top-left corner (20% x 20%)
- `top-right` - Top-right corner (20% x 20%)
- `bottom-left` - Bottom-left corner (20% x 20%)
- `bottom-right` - Bottom-right corner (20% x 20%)
- `center` - Center region (40% x 40%)

## Multi-ROI (Watermarks Only)

For watermark removal, you can specify multiple ROIs separated by commas:

```bash
--watermark-roi 'top-right,bottom-left'
```

This will detect and remove watermarks in both locations.

## Command Examples

### Remove subtitles from bottom half
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi '0.0,0.5,1.0,0.5'
```

### Remove watermark from top-right
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi 'top-right'
```

### Remove watermarks from multiple corners
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi 'top-right,bottom-left'
```

## Visual Reference

For a 1920x1080 frame with ROI `'0.0,0.5,1.0,0.4'`:

```
┌─────────────────────────────┐ 0% (y=0)
│                             │
│      (Out of ROI)           │
│                             │
├─────────────────────────────┤ 50% (y=540) ← ROI starts here
│█████████████████████████████│
│█████████████████████████████│ ROI Region
│█████████████████████████████│ (Full width, 40% height)
│█████████████████████████████│
├─────────────────────────────┤ 90% (y=972) ← ROI ends here
│                             │
│      (Out of ROI)           │
└─────────────────────────────┘ 100% (y=1080)
```

Only text detected within the shaded ROI region will be removed.

## Important Notes

1. **Coordinates are normalized**: Values must be between 0.0 and 1.0
2. **Format is x,y,w,h**: Not x1,y1,x2,y2 (that's the old format)
3. **Y grows downward**: y=0.0 is top, y=1.0 is bottom
4. **ROI is applied before OCR**: This speeds up processing by 50-70%
5. **Text outside ROI is ignored**: Use `--roi full` to process entire frame

## Migration from Old Format

If you used the old `x1,y1,x2,y2` format:

**Old format** (x1,y1,x2,y2 - two corners):
```bash
--roi '0.0,0.5,1.0,1.0'  # Old: top-left (0,0.5) to bottom-right (1.0,1.0)
```

**New format** (x,y,w,h - position + size):
```bash
--roi '0.0,0.5,1.0,0.5'  # New: start at (0,0.5), size (1.0,0.5)
```

Both describe the same region (bottom half), but the new format is more intuitive.

