# Deprecated Legacy Code (Removed Dec 2025)

This document lists legacy code that was permanently removed in December 2025 as part of the transition to Clean Architecture and Native Python Processors.

---

## ⚠️ Breaking Changes

### Legacy Entry Point Removed
**File**: `pipeline.py` (900 lines)  
**Removed**: December 8, 2025  
**Replaced by**: `pipeline_v2.py`

**Reason**: Monolithic design, hard to debug, no tests, tight coupling with bash scripts.

**Migration**:
```bash
# OLD (no longer works):
python pipeline.py --input video.mp4 --output output/ --mode both

# NEW (use this):
python pipeline_v2.py --input video.mp4 --output output/ --mode both
```

---

## 🗑️ Removed Files

### 1. Bash Wrapper Scripts

#### `run_realesrgan_pytorch.sh` (977 lines)
- **Purpose**: Wrapper for Real-ESRGAN PyTorch implementation
- **Replaced by**: `src/infrastructure/processors/realesrgan/native.py`
- **Reason**: Bash is hard to debug, no breakpoint support

#### `run_rife_pytorch.sh` (1,097 lines)
- **Purpose**: Wrapper for RIFE PyTorch implementation
- **Replaced by**: `src/infrastructure/processors/rife/native.py`
- **Reason**: Bash is hard to debug, no breakpoint support

#### `realesrgan_batch_safe.sh` (~500 lines)
- **Purpose**: Batch processing for Real-ESRGAN
- **Replaced by**: Native Python implementation in `native.py`
- **Reason**: Simplified architecture, better error handling

**Total bash code removed**: ~2,574 lines

---

### 2. Deprecated Python Wrappers

#### `src/infrastructure/processors/realesrgan/pytorch_wrapper.py`
- **Purpose**: Python wrapper calling bash script
- **Replaced by**: `native.py` (direct Python implementation)
- **Reason**: Indirection layer no longer needed

#### `src/infrastructure/processors/rife/pytorch_wrapper.py`
- **Purpose**: Python wrapper calling bash script
- **Replaced by**: `native.py` (direct Python implementation)
- **Reason**: Indirection layer no longer needed

---

## 📊 Impact Summary

### Code Removed
```
pipeline.py:                    900 lines
run_realesrgan_pytorch.sh:      977 lines
run_rife_pytorch.sh:          1,097 lines
realesrgan_batch_safe.sh:      ~500 lines
pytorch_wrapper.py files:      ~200 lines
─────────────────────────────────────────
TOTAL:                        ~3,674 lines
```

### Benefits
- ✅ **-3,674 lines** of legacy code removed
- ✅ **100% Python** - no bash dependencies
- ✅ **Full IDE debugging** - breakpoints work
- ✅ **Clean Architecture** - SOLID principles
- ✅ **Better testability** - 78 unit tests
- ✅ **Easier maintenance** - single entry point

---

## 🔄 Migration Guide

### For Developers

If you have local scripts or automation using the old entry point:

**Before (legacy)**:
```bash
python pipeline.py \
  --input video.mp4 \
  --output output/ \
  --mode both \
  --scale 2 \
  --target-fps 60
```

**After (current)**:
```bash
python pipeline_v2.py \
  --input video.mp4 \
  --output output/ \
  --mode both \
  --scale 2 \
  --target-fps 60
```

**Arguments remain the same!** Only the script name changed.

---

### For Docker/Production

**Container environments automatically use `pipeline_v2.py`** via:
- `scripts/container_config_runner.py` (updated)
- `scripts/remote_runner.sh` (updated)

No changes needed to your deployment scripts if you use config-driven workflows.

---

### For CI/CD

Update your pipeline scripts:

```yaml
# OLD
script:
  - python pipeline.py --mode upscale --input test.mp4

# NEW
script:
  - python pipeline_v2.py --mode upscale --input test.mp4
```

---

## 🐛 Debugging Improvements

### Before (Legacy)
```bash
# Bash wrapper - no debugging possible
./run_realesrgan_pytorch.sh input.mp4 output.mp4 2

# Errors were cryptic:
# line 487: syntax error near unexpected token
```

### After (Native Python)
```python
# Full Python - set breakpoints in PyCharm!
from infrastructure.processors.realesrgan.native import RealESRGANNative

processor = RealESRGANNative(scale=2)
output = processor.process_frames(frames, output_dir)  # <- BREAKPOINT HERE

# Stack traces are meaningful:
# File "native.py", line 123, in process_frames
#   raise ValueError(f"Invalid scale: {scale}")
```

---

## 📚 Documentation References

### Updated Documentation
- `README.md` - Updated with migration guide
- `docs/LEGACY_CLEANUP_PLAN.md` - Detailed cleanup plan
- This file (`DEPRECATED.md`)

### Relevant Guides
- `docs/NATIVE_PROCESSORS_GUIDE.md` - Native Python processors
- `docs/NATIVE_QUICK_START.md` - Quick start (3 steps)
- `docs/DEBUG_MODE_GUIDE.md` - Debugging guide
- `docs/oop3.md` - Architecture details

---

## 🔍 Git History

You can still view the legacy code in Git history:

```bash
# View last version before removal
git show legacy-before-cleanup:pipeline.py

# View bash wrapper
git show legacy-before-cleanup:run_realesrgan_pytorch.sh

# See removal commit
git show 8ebbde5

# Browse at specific commit
git checkout legacy-before-cleanup
# (read-only - don't commit from here!)
git checkout main
```

---

## ❓ FAQ

### Q: Why was this removed?
**A**: Legacy code created technical debt:
- Bash scripts are hard to debug (no breakpoints)
- Monolithic design violated SOLID principles
- No test coverage
- Maintenance burden

### Q: Can I still use the old code?
**A**: No. Legacy code is permanently removed. Use `pipeline_v2.py`.

### Q: What if I find a reference to `pipeline.py`?
**A**: 
1. Update it to `pipeline_v2.py`
2. Report it via issue tracker if it's in production code
3. Check this guide for migration examples

### Q: Will old Docker images still work?
**A**: Old images will look for bash scripts and fail. Rebuild with latest code:
```bash
docker build -t your-image:latest .
```

### Q: Performance differences?
**A**: **Native Python is same speed** as bash wrappers (both use same ML libraries underneath). The change is architectural, not algorithmic.

---

## 🎯 Success Metrics

- ✅ Codebase reduced by 3,674 lines (12% reduction)
- ✅ Single entry point (`pipeline_v2.py`)
- ✅ 100% Python (no bash)
- ✅ Full debugging support
- ✅ All tests passing (78 unit + 12 integration)
- ✅ Production deployments updated

---

## 📅 Timeline

- **December 1, 2025**: Native processors implemented
- **December 8, 2025**: Legacy code removed (this document created)
- **December 8, 2025**: Git tag `legacy-before-cleanup` created
- **December 8, 2025**: Production scripts updated

---

## 📞 Support

If you encounter issues after this change:

1. **Check migration guide** (above)
2. **Review README.md** for current usage
3. **Check Git history** if you need to reference old code
4. **Open an issue** if you find bugs

---

**Last Updated**: December 8, 2025  
**Removal Commit**: 8ebbde5  
**Safety Tag**: `legacy-before-cleanup`
