# ROI Format Migration Guide

## ⚠️ Breaking Change: ROI Format Updated

**Date**: January 9, 2026  
**Version**: v2.1.0+

---

## What Changed?

The ROI (Region of Interest) parameter format has been updated for better clarity and consistency:

### Old Format (Deprecated)
```bash
--roi 'x1,y1,x2,y2'  # Two corner points
```
- x1,y1 = top-left corner
- x2,y2 = bottom-right corner

### New Format (Current)
```bash
--roi 'x,y,w,h'  # Position + size
```
- x,y = top-left corner position
- w,h = width and height (size)

---

## Why the Change?

The new format is:
1. **More intuitive**: Position + size is easier to understand than two corner points
2. **Consistent**: Matches standard image processing conventions (OpenCV, PIL, etc.)
3. **Less error-prone**: No confusion about which corner is which

---

## Migration Examples

### Example 1: Bottom Half of Frame

**Old format:**
```bash
--roi '0.0,0.5,1.0,1.0'
# x1=0.0, y1=0.5 (top-left at 50% down)
# x2=1.0, y2=1.0 (bottom-right at 100%)
```

**New format:**
```bash
--roi '0.0,0.5,1.0,0.5'
# x=0.0, y=0.5 (start at 50% down)
# w=1.0, h=0.5 (span 100% width, 50% height)
```

### Example 2: Your Specific Case

**Your command (old format interpretation):**
```bash
--roi '0.0,0.5,1.0,0.4'
# Old: Would be interpreted as top-left (0.0, 0.5) to bottom-right (1.0, 0.4)
# Problem: y2 < y1 → INVALID!
```

**Correct new format:**
```bash
--roi '0.0,0.5,1.0,0.4'
# New: Start at (0.0, 0.5), size (1.0, 0.4)
# Result: Region from 50% to 90% of frame height ✓
```

### Example 3: Top-Right Corner (Watermark)

**Old format:**
```bash
--roi '0.8,0.0,1.0,0.2'
# x1=0.8, y1=0.0 → x2=1.0, y2=0.2
```

**New format:**
```bash
--roi '0.8,0.0,0.2,0.2'
# x=0.8, y=0.0, w=0.2, h=0.2
```

---

## Quick Conversion Formula

If you have old format `x1,y1,x2,y2`:

```python
# Old format
x1, y1, x2, y2 = 0.0, 0.5, 1.0, 1.0

# Convert to new format
x = x1
y = y1
w = x2 - x1
h = y2 - y1

# Result
# x=0.0, y=0.5, w=1.0, h=0.5
```

---

## How to Update Your Scripts

### 1. Find all --roi usage
```bash
grep -r "\-\-roi" your_scripts/
```

### 2. Check if you use custom coordinates
If you use presets (`bottom`, `top`, `full`), **no changes needed**!

Presets still work:
```bash
--roi bottom   # ✓ Still works
--roi top      # ✓ Still works
--roi full     # ✓ Still works
```

### 3. Update custom coordinates

**Before (old):**
```bash
--roi '0.0,0.6,1.0,1.0'  # Bottom 40%
```

**After (new):**
```bash
--roi '0.0,0.6,1.0,0.4'  # Bottom 40%
```

---

## Validation

To verify your ROI is correct, check the logs:

### Successful parsing:
```
[cleaner_service] SubtitleRemoverService initialized:
  - ROI: Custom ROI (x=0.00, y=0.50, w=1.00, h=0.40)
```

### Fallback to default (failed parsing):
```
[cleaner_service] ❌ Invalid ROI: coordinates must be in range [0.0, 1.0]: ...
[cleaner_service]    Using default ROI (bottom 60%)
```

---

## Need Help?

### Visual Tool
See [docs/ROI_FORMAT.md](./ROI_FORMAT.md) for visual examples and reference.

### Common Issues

**Issue 1: "Using default ROI (bottom 60%)"**
- Your ROI format is invalid
- Check that all values are between 0.0 and 1.0
- Ensure format is exactly `x,y,w,h` with 4 values

**Issue 2: "zero-area region"**
- Width (w) or height (h) is 0 or negative
- Make sure w > 0 and h > 0

**Issue 3: ROI not covering expected area**
- Remember: y=0 is TOP, y=1 is BOTTOM
- Region spans from (x,y) to (x+w, y+h)

---

## Testing Your ROI

Quick test command (dry run, processes only 1 frame):
```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-subtitles \
  --roi '0.0,0.5,1.0,0.4' \
  --debug  # Saves diagnostic images showing ROI boundaries
```

Check the debug output in `output/debug/` to verify ROI placement.

---

## Backward Compatibility

⚠️ **Important**: The system will attempt to parse your ROI, but if it fails validation, it will fall back to the default `bottom` preset (60% from bottom).

**Always check logs** after updating to ensure your ROI is parsed correctly!

---

## Summary

| Aspect | Old Format | New Format |
|--------|------------|------------|
| **Syntax** | `x1,y1,x2,y2` | `x,y,w,h` |
| **Meaning** | Two corners | Position + size |
| **Example** | `0.0,0.5,1.0,1.0` | `0.0,0.5,1.0,0.5` |
| **Presets** | ✓ Supported | ✓ Supported |

**Bottom line**: If you used presets, no action needed. If you used custom coordinates, update them using the conversion formula above.

