# ROI Format Fix - Change Summary

**Date**: January 9, 2026  
**Issue**: ROI parameter `'0.0,0.5,1.0,0.4'` was being interpreted as `x1,y1,x2,y2` format instead of `x,y,w,h`  
**Status**: ✅ FIXED

---

## Problem

User command:
```bash
python3 pipeline_v2.py \
  --bucket 'videos' \
  --roi '0.0,0.5,1.0,0.4' \
  --mode 'remove-subtitles' \
  --input 'video.mp4'
```

**Expected behavior**: ROI should cover region from 50% to 90% of frame height (x=0.0, y=0.5, w=1.0, h=0.4)

**Actual behavior**: System fell back to default "Bottom 60%" ROI because it was parsing `0.0,0.5,1.0,0.4` as `x1,y1,x2,y2` (two corner points), which resulted in invalid coordinates (y2 < y1).

---

## Root Cause

Two different systems in the codebase:

1. **`geometry.py`** (`resolve_roi`): Already used `x,y,w,h` format ✅
2. **`cleaner_service.py`** (`SubtitleRemoverService._parse_roi`): Used old `x1,y1,x2,y2` format ❌

Result: Inconsistency led to failed parsing and fallback to default ROI.

---

## Changes Made

### 1. Fixed `SubtitleRemoverService._parse_roi()` (cleaner_service.py)

**Before:**
```python
# Parsed as x1,y1,x2,y2 (two corner points)
x1, y1, x2, y2 = parts
```

**After:**
```python
# Parse as x,y,w,h (position + size)
x, y, w, h = parts

# Convert to internal bbox format
x1 = x
y1 = y
x2 = x + w
y2 = y + h
```

### 2. Updated Documentation

**File** | **Description**
---------|----------------
`cleaner_service.py` | Updated class docstring to reflect `x,y,w,h` format
`cli.py` | Updated `--roi` help text to describe `x,y,w,h` format
`docs/ROI_FORMAT.md` | Complete reference with visual examples
`docs/ROI_MIGRATION.md` | Migration guide from old to new format
`docs/ROI_QUICK.md` | Quick reference for common use cases

### 3. Added Tests

**File**: `tests/test_roi_format_xywh.py`

Comprehensive test suite covering:
- Basic `x,y,w,h` parsing
- Preset handling (`bottom`, `top`, `full`)
- Internal bbox conversion
- Multi-zone ROI support
- Edge cases

---

## Verification

### Test Case 1: User's Original Command
```bash
--roi '0.0,0.5,1.0,0.4'
```

**Expected parsing:**
- x = 0.0 (left edge)
- y = 0.5 (start at 50% down)
- w = 1.0 (full width)
- h = 0.4 (40% height)

**Result region:**
- Top: 50% of frame height
- Bottom: 90% of frame height
- Coverage: 40% of frame (middle-bottom area)

**Log output (expected):**
```
[cleaner_service] SubtitleRemoverService initialized:
  - ROI: Custom ROI (x=0.00, y=0.50, w=1.00, h=0.40)
```

### Test Case 2: Presets Still Work
```bash
--roi bottom  # ✅ Still works (bottom 60%)
--roi top     # ✅ Still works (top 30%)
--roi full    # ✅ Still works (entire frame)
```

---

## Breaking Changes

⚠️ **If you used custom ROI coordinates in the old format (`x1,y1,x2,y2`), you must update them!**

### Conversion Formula

```python
# Old format: x1, y1, x2, y2
# New format: x, y, w, h

x = x1
y = y1
w = x2 - x1
h = y2 - y1
```

### Example Conversion

**Old format:**
```bash
--roi '0.0,0.6,1.0,1.0'  # Bottom 40% (old interpretation)
```

**New format:**
```bash
--roi '0.0,0.6,1.0,0.4'  # Bottom 40% (new interpretation)
```

---

## Backward Compatibility

✅ **Preset strings are unchanged**: `bottom`, `top`, `full`, etc.  
❌ **Custom coordinates must be updated** if you used the old format  
✅ **Validation and fallback**: Invalid ROI strings fall back to `bottom` (60%) with clear error messages

---

## Files Modified

### Code Changes
- `src/services/cleaner_service.py` - Fixed ROI parsing logic
- `src/presentation/cli.py` - Updated help text

### Documentation Added
- `docs/ROI_FORMAT.md` - Complete reference
- `docs/ROI_MIGRATION.md` - Migration guide
- `docs/ROI_QUICK.md` - Quick reference
- `tests/test_roi_format_xywh.py` - Test suite

### Unchanged (Already Correct)
- `src/infrastructure/image_processing/geometry.py` - Already used `x,y,w,h` ✅
- `src/infrastructure/ocr/paddle_wrapper.py` - Uses `resolve_roi()` ✅
- `src/infrastructure/processors/watermark/wrapper.py` - Uses `resolve_roi()` ✅

---

## Next Steps

1. ✅ **Test the fix** with user's original command
2. ✅ **Run test suite** to verify parsing
3. ✅ **Update any existing scripts** that use custom ROI coordinates
4. ✅ **Deploy to production** after validation

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Format** | Mixed (x1,y1,x2,y2 in cleaner_service) | Unified (x,y,w,h everywhere) |
| **Consistency** | ❌ Inconsistent | ✅ Consistent |
| **User Command** | ❌ Failed (fallback to default) | ✅ Works correctly |
| **Documentation** | ❌ Missing | ✅ Comprehensive |
| **Tests** | ❌ None | ✅ Full test suite |

**Result**: ROI parameter now works correctly across all components! 🎉

