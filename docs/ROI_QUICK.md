# ROI Quick Reference

## TL;DR

ROI format is `x,y,w,h` where all values are 0.0 to 1.0:
- **x**: horizontal position (0.0 = left)
- **y**: vertical position (0.0 = top)
- **w**: width (fraction of frame width)
- **h**: height (fraction of frame height)

## Common Examples

```bash
# Bottom half of frame (default for subtitles)
--roi '0.0,0.5,1.0,0.5'

# Your specific case: 50% to 90% vertically
--roi '0.0,0.5,1.0,0.4'

# Top-right corner (watermark)
--roi '0.8,0.0,0.2,0.2'

# Or use presets:
--roi bottom    # Bottom 60% (default)
--roi top       # Top 30%
--roi full      # Entire frame
```

## Visual

```
Frame (1920x1080) with ROI '0.0,0.5,1.0,0.4':

0%   ┌─────────────────┐
     │                 │ ← Out of ROI
     │                 │
50%  ├─────────────────┤ ← ROI starts (y=0.5)
     │█████████████████│
     │█████████████████│ ← ROI region (height=0.4)
     │█████████████████│
90%  ├─────────────────┤ ← ROI ends (y+h=0.9)
     │                 │ ← Out of ROI
100% └─────────────────┘
```

## Need More?

See detailed docs:
- [ROI_FORMAT.md](./ROI_FORMAT.md) - Complete reference with examples
- [ROI_MIGRATION.md](./ROI_MIGRATION.md) - Migration guide from old format

