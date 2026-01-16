# ROI Parsing Issue - Diagnosis and Fix

## Problem

When running:
```bash
python3 pipeline_v2.py --roi '0.0,0.5,1.0,0.4' --mode 'remove-subtitles' ...
```

The system fell back to default ROI (bottom 60%) instead of using the specified bounding box.

## Root Cause

**Your ROI string:** `'0.0,0.5,1.0,0.4'`

Format: `x1, y1, x2, y2` (normalized coordinates 0.0-1.0)
- `x1 = 0.0` (left edge, 0%)
- `y1 = 0.5` (top edge, 50% from top)
- `x2 = 1.0` (right edge, 100%)
- `y2 = 0.4` (bottom edge, 40% from top) ❌

**Validation failed because:** `y2 > y1` is required, but `0.4 > 0.5` is **FALSE**

The bounding box had inverted Y-coordinates (bottom is higher than top), which is geometrically invalid.

## What You Probably Meant

### Option 1: Bottom Half of Screen
```bash
--roi '0.0,0.5,1.0,1.0'
```
- From y=0.5 (50% from top) to y=1.0 (bottom)
- Covers bottom 50% of screen

### Option 2: Bottom 40% of Screen
```bash
--roi '0.0,0.6,1.0,1.0'
```
- From y=0.6 (60% from top) to y=1.0 (bottom)
- Covers bottom 40% of screen

### Option 3: Specific Region (40% to 90% from top)
```bash
--roi '0.0,0.4,1.0,0.9'
```
- From y=0.4 to y=0.9
- Covers middle region (50% of screen height)

## Fix Applied

The code has been updated with:

1. **Auto-correction of inverted coordinates**
   - If `y2 < y1`, the system will automatically swap them
   - Warning message will be logged

2. **Better error messages**
   - Clear explanation of what went wrong
   - Expected format examples
   - Validation requirements

3. **Detailed logging**
   - Shows parsed bounding box
   - Shows width and height of region
   - Shows why validation failed (if it does)

## ROI Format Reference

### Bounding Box Format
```
--roi 'x1,y1,x2,y2'
```
Where:
- `x1` = left edge (0.0 = left side, 1.0 = right side)
- `y1` = **top** edge (0.0 = top, 1.0 = bottom)
- `x2` = right edge (must be > x1)
- `y2` = **bottom** edge (must be > y1)

### Common Presets
```bash
--roi 'bottom'    # Bottom 60% (default)
--roi 'top'       # Top 60%
--roi 'full'      # Entire screen
--roi '0.6'       # Bottom 60% (numeric)
```

## Examples

### Subtitle at Bottom
```bash
--roi '0.0,0.7,1.0,1.0'  # Bottom 30% of screen
```

### Subtitle in Middle
```bash
--roi '0.0,0.4,1.0,0.6'  # Middle 20% (from 40% to 60%)
```

### Wide Bottom Region
```bash
--roi '0.1,0.6,0.9,1.0'  # Bottom 40%, but only center 80% width
```

### Specific Corner (for watermarks)
```bash
--roi '0.8,0.0,1.0,0.2'  # Top-right corner (20% height, 20% width)
```

## Testing Your ROI

Run the test script:
```bash
python test_roi_parsing.py
```

This will show exactly how your ROI string is parsed and what region it represents.

## Correct Command for Your Case

If you wanted **bottom half of screen**:
```bash
python3 pipeline_v2.py \
  --bucket 'videos' \
  --b2-endpoint 'https://...' \
  --b2-region 'EEUR' \
  --roi '0.0,0.5,1.0,1.0' \  # ✅ Corrected: y1=0.5, y2=1.0
  --mode 'remove-subtitles' \
  --input 'https://...' \
  --subs-lang 'en' \
  --job '...'
```

## Next Steps

1. ✅ **Fix applied** - Auto-correction of inverted coordinates
2. ✅ **Better logging** - Clear error messages
3. 🔄 **Re-run your command** with corrected ROI
4. 📝 **Check logs** for ROI parsing confirmation

The system will now:
- Detect inverted coordinates
- Swap them automatically
- Log a warning message
- Continue processing with corrected ROI

Or if the error is severe (zero-area box), it will:
- Log detailed error message
- Explain what went wrong
- Fall back to default ROI (bottom 60%)
- Continue processing safely

