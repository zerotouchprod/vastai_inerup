# ROI Cheat Sheet

## Format: x,y,w,h (all values 0.0 to 1.0)

```
x = horizontal start position (0.0=left, 1.0=right)
y = vertical start position (0.0=top, 1.0=bottom)
w = width (fraction of frame width)
h = height (fraction of frame height)
```

## Common Presets

```bash
--roi bottom       # Bottom 60% (default for subtitles)
--roi top          # Top 30%
--roi full         # Entire frame
--roi top-right    # Top-right corner (watermark)
--roi bottom-left  # Bottom-left corner
```

## Custom ROI Examples

```bash
# Bottom half
--roi '0.0,0.5,1.0,0.5'

# Bottom 40% (from 60% to 100%)
--roi '0.0,0.6,1.0,0.4'

# Middle region (50% to 90%)
--roi '0.0,0.5,1.0,0.4'

# Top-right corner (20% x 20%)
--roi '0.8,0.0,0.2,0.2'

# Right edge strip (15% width, full height)
--roi '0.85,0.0,0.15,1.0'
```

## Command Examples

```bash
# Remove subtitles from bottom half
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi '0.0,0.5,1.0,0.5'

# Remove watermark from top-right
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi 'top-right'

# Remove multiple watermarks
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-watermark \
  --watermark-roi 'top-right,bottom-left'
```

## Visual Calculator

```
Frame: 1920x1080
ROI: '0.0,0.5,1.0,0.4'

Result:
  x = 0 (0.0 * 1920)
  y = 540 (0.5 * 1080)
  w = 1920 (1.0 * 1920)
  h = 432 (0.4 * 1080)

Region: 0,540 to 1920,972
Coverage: 50% to 90% of height
```

## Tips

✅ Use presets when possible (faster, clearer)  
✅ Test with `--debug` to see ROI boundaries  
✅ Check logs for parsing confirmation  
❌ Don't use negative values  
❌ Don't use values > 1.0  
❌ Don't make w or h zero

