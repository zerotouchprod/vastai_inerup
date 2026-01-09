# GPU Validation & ROI Parsing Fix - Implementation Summary

## Completed Implementation

### Phase 1: GPU Validation System ✅

#### 1.1 New Exception Type
**File:** `src/domain/exceptions.py`
- ✅ Added `GPURequiredError` exception class
- Inherits from `DomainException`
- Used for clear error messaging when GPU is required but unavailable

#### 1.2 GPU Utilities Module
**File:** `src/infrastructure/utils/gpu_utils.py` (NEW)
- ✅ `check_gpu_available()` - Check if CUDA GPU is available
- ✅ `get_gpu_info()` - Get detailed GPU info (device name, VRAM, etc.)
- ✅ `require_gpu(operation_name)` - Enforce GPU requirement with clear error
- ✅ `log_gpu_status()` - Log GPU diagnostics

#### 1.3 Processor Updates
**Files Modified:**
- `src/services/cleaner_service.py` (SubtitleRemoverService)
- `src/infrastructure/processors/subtitle/native.py` (SubtitleRemoverNative)
- `src/infrastructure/processors/watermark/wrapper.py` (WatermarkRemoverWrapper)

**Changes:**
- ✅ Added `require_gpu()` call in `__init__()` methods
- ✅ Raises `GPURequiredError` immediately if GPU not available
- ✅ Prevents slow CPU processing (which would take hours)

#### 1.4 Factory Updates
**File:** `src/application/factories.py`
- ✅ Added early GPU check in `create_subtitle_remover()`
- ✅ Added early GPU check in `create_watermark_remover()`
- ✅ Fails fast before creating any expensive components

#### 1.5 CLI Error Handling
**File:** `src/presentation/cli.py`
- ✅ Added `GPURequiredError` to imports
- ✅ Added dedicated exception handler with helpful error message
- ✅ Returns exit code 2 for GPU requirement errors
- ✅ Suggests solutions to users

### Phase 2: ROI Parsing Fix ✅

#### 2.1 Problem Identified
**User Command:**
```bash
--roi '0.0,0.5,1.0,0.4'
```

**Issue:** Inverted Y-coordinates
- `y1 = 0.5` (top edge)
- `y2 = 0.4` (bottom edge) ❌
- Validation failed: `y2 > y1` was FALSE (`0.4 > 0.5` = FALSE)
- System fell back to default ROI (bottom 60%)

#### 2.2 Fix Implemented
**File:** `src/services/cleaner_service.py` - `_parse_roi()` method

**Improvements:**
1. ✅ **Auto-correction of inverted coordinates**
   - Detects `x2 < x1` and swaps them
   - Detects `y2 < y1` and swaps them
   - Logs warning messages

2. ✅ **Enhanced error messages**
   - Clear explanation of validation failure
   - Shows corrected coordinates
   - Provides format examples
   - Explains requirements

3. ✅ **Better logging**
   - Shows parsed bounding box with dimensions
   - Displays width and height
   - Uses ✅/❌ emojis for clarity

### Phase 3: Testing & Documentation ✅

#### 3.1 Test Scripts Created
1. **`test_gpu_validation.py`**
   - Tests GPU detection
   - Tests processor creation with/without GPU
   - Validates error handling

2. **`test_roi_parsing.py`**
   - Tests various ROI formats
   - Tests auto-correction
   - Tests error handling

#### 3.2 Documentation Created
1. **`ROI_PARSING_FIX.md`**
   - Detailed problem explanation
   - Root cause analysis
   - Correct ROI format examples
   - Common use cases
   - Testing instructions

## Behavior Changes

### Before Fix

**ROI Parsing:**
```
Input: --roi '0.0,0.5,1.0,0.4'
Result: ⚠️ Invalid bounding box coordinates, using default
Action: Silently falls back to bottom 60%
```

**GPU Requirement:**
```
Input: --mode remove-subtitles (on CPU machine)
Result: ⚠️ GPU not available, using CPU
Action: Continues processing on CPU (VERY SLOW)
```

### After Fix

**ROI Parsing:**
```
Input: --roi '0.0,0.5,1.0,0.4'
Result: ⚠️ ROI y-coordinates inverted (y2 < y1), swapping: 0.5,0.4 -> 0.4,0.5
        ✅ ROI: Bounding box (0.00,0.40,1.00,0.50) - width=1.00, height=0.10
Action: Processes with corrected ROI
```

**GPU Requirement:**
```
Input: --mode remove-subtitles (on CPU machine)
Result: ❌ GPU REQUIRED
        GPU required for subtitle removal
        CPU processing is disabled (too slow, would take hours).
        Please run on GPU-enabled instance with CUDA support.
Action: Exits with code 2 (GPU requirement not met)
```

## Exit Codes

- **0** - Success
- **1** - General error (domain exception, processing failed)
- **2** - GPU requirement not met (NEW)
- **130** - Keyboard interrupt

## Correct ROI Examples

### Subtitle Removal (Bottom Region)
```bash
# Bottom half of screen
--roi '0.0,0.5,1.0,1.0'

# Bottom 40%
--roi '0.0,0.6,1.0,1.0'

# Bottom 30%
--roi '0.0,0.7,1.0,1.0'

# Middle region (40% to 60% from top)
--roi '0.0,0.4,1.0,0.6'
```

### Watermark Removal (Corner/Edge)
```bash
# Top-right corner
--roi '0.8,0.0,1.0,0.2'

# Top-left corner
--roi '0.0,0.0,0.2,0.2'

# Bottom-right corner
--roi '0.8,0.8,1.0,1.0'

# Center watermark
--roi '0.4,0.4,0.6,0.6'
```

## Usage Examples

### Correct Command (Fixed)
```bash
python3 pipeline_v2.py \
  --bucket 'videos' \
  --b2-endpoint 'https://...' \
  --b2-region 'EEUR' \
  --roi '0.0,0.5,1.0,1.0' \  # ✅ Corrected
  --mode 'remove-subtitles' \
  --input 'https://...' \
  --subs-lang 'en' \
  --job '...'
```

### Testing GPU Validation
```bash
# Test GPU detection
python test_gpu_validation.py

# Test ROI parsing
python test_roi_parsing.py
```

## Files Changed

1. ✅ `src/domain/exceptions.py` - Added GPURequiredError
2. ✅ `src/infrastructure/utils/gpu_utils.py` - NEW - GPU utilities
3. ✅ `src/services/cleaner_service.py` - GPU check + ROI fix
4. ✅ `src/infrastructure/processors/subtitle/native.py` - GPU check
5. ✅ `src/infrastructure/processors/watermark/wrapper.py` - GPU check + minor fixes
6. ✅ `src/application/factories.py` - Early GPU validation
7. ✅ `src/presentation/cli.py` - GPU error handling
8. ✅ `test_gpu_validation.py` - NEW - Test script
9. ✅ `test_roi_parsing.py` - NEW - Test script
10. ✅ `ROI_PARSING_FIX.md` - NEW - Documentation

## Next Steps

1. **Re-run your command** with corrected ROI:
   ```bash
   --roi '0.0,0.5,1.0,1.0'  # For bottom half
   ```

2. **Check logs** for ROI parsing confirmation:
   ```
   ✅ ROI: Bounding box (0.00,0.50,1.00,1.00) - width=1.00, height=0.50
   ```

3. **Verify GPU detection** on your instance:
   ```bash
   python test_gpu_validation.py
   ```

4. **If running on CPU**, you'll now get:
   ```
   ❌ GPU REQUIRED
   GPU required for subtitle removal
   CPU processing is disabled (too slow, would take hours).
   Please run on GPU-enabled instance with CUDA support.
   ```

## Summary

✅ **GPU validation** - Prevents slow CPU processing for subtitle/watermark removal  
✅ **ROI auto-correction** - Fixes inverted coordinates automatically  
✅ **Better error messages** - Clear, actionable feedback  
✅ **Comprehensive tests** - Validates both GPU and ROI parsing  
✅ **Full documentation** - Complete guide for ROI format  

The system now:
- **Fails fast** when GPU is required but unavailable
- **Auto-corrects** common ROI mistakes
- **Provides clear feedback** with detailed error messages
- **Continues safely** with corrected parameters when possible

