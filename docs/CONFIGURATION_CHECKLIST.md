# Quick Configuration Checklist

## ✅ Files Created (6 files)

### Configuration Modules
- [x] `src/infrastructure/processors/subtitle_removal_config.py` (348 lines)
- [x] `src/infrastructure/processors/watermark_removal_config.py` (386 lines)

### Documentation
- [x] `docs/TUNING_GUIDE.md` (521 lines) - Complete tuning guide
- [x] `docs/CONFIG_SYSTEM_SUMMARY.md` - Quick reference
- [x] `docs/ROI_FIX_SUMMARY.md` - ROI format fix summary (previous task)
- [x] `ROI_CHEATSHEET.md` - ROI cheat sheet (previous task)

## ✅ Files Modified (3 files)

- [x] `src/services/cleaner_service.py` - Uses `subtitle_removal_config`
- [x] `src/infrastructure/processors/watermark/wrapper.py` - Uses `watermark_removal_config`
- [x] `src/infrastructure/image_processing/watermark_detector.py` - Uses `watermark_removal_config`

## 📊 Parameters Now Configurable

### Subtitle Removal (14 params)
- [x] OCR confidence threshold
- [x] Dual-pass OCR enable/disable
- [x] IoU threshold for deduplication
- [x] Horizontal bbox expansion
- [x] Vertical bbox expansion
- [x] VRAM-adaptive kernel sizes (3 tiers)
- [x] Initial dilation iterations
- [x] Morphological closing iterations
- [x] Final dilation iterations
- [x] CLAHE clip limit
- [x] CLAHE tile grid size
- [x] GPU cleanup interval
- [x] Progress logging percentage
- [x] Debug max filtered examples

### Watermark Removal (15 params)
- [x] Persistence threshold
- [x] Sample frame count
- [x] Min region area
- [x] Max region area ratio
- [x] Color detection enable/disable
- [x] Color diff threshold
- [x] Edge detection low threshold
- [x] Edge detection high threshold
- [x] Edge dilation kernel
- [x] Mask expansion radius
- [x] Morphological closing kernel
- [x] Mask blur sigma
- [x] Detection scale factor
- [x] OCR fallback confidence
- [x] OCR fallback expansion

## 🎨 Preset Profiles

### Subtitle Removal
- [x] `conservative` - Minimal false positives
- [x] `balanced` - Default recommended
- [x] `aggressive` - Catch all text
- [x] `minimal` - Only obvious text

### Watermark Removal
- [x] `opaque_logo` - Solid channel logos
- [x] `transparent_overlay` - Semi-transparent watermarks
- [x] `small_text` - Copyright notices
- [x] `large_banner` - TV station bugs
- [x] `animated_watermark` - Fading/animated logos

## 🔧 Features

- [x] Centralized configuration (2 files instead of scattered hardcoded values)
- [x] Detailed comments for each parameter (Russian + English)
- [x] Range recommendations for each parameter
- [x] Built-in validation with warnings
- [x] Profile system for common use cases
- [x] Environment variable override support (`FORCE_KERNEL_SIZE`)
- [x] Helper functions (get_kernel_size_for_vram, print_current_config, etc.)
- [x] Backward compatible (old code works without changes)

## 📚 Documentation

- [x] Complete tuning guide with examples
- [x] Problem-solution scenarios
- [x] Parameter reference tables
- [x] Testing instructions
- [x] Custom profile creation examples

## 🧪 Test Scenarios Documented

- [x] "Removes too much" → reduce aggressiveness
- [x] "Misses some text" → increase sensitivity
- [x] "Too slow" → optimize performance
- [x] "Colored watermarks not detected" → enable color detection
- [x] "Leaves artifacts" → increase expansion/smoothing

## ✅ Ready to Use

All parameters are now tunable via configuration files!

### To start tuning:

1. Open config file:
   - Subtitles: `src/infrastructure/processors/subtitle_removal_config.py`
   - Watermarks: `src/infrastructure/processors/watermark_removal_config.py`

2. Edit parameters or apply profile:
   ```python
   from src.infrastructure.processors import subtitle_removal_config as SRC
   SRC.apply_profile('aggressive')
   ```

3. Test with debug mode:
   ```bash
   python3 pipeline_v2.py --input video.mp4 --mode remove-subtitles --debug
   ```

4. Check masks in `output/debug/`

5. Iterate and adjust!

---

**Status**: ✅ **COMPLETE AND READY TO USE**

