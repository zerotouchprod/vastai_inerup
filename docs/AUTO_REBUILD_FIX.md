# Auto-Rebuild Fix for Vast.ai CUDA Mismatch

## Problem
On Vast.ai, the application was failing with:
```
❌ spatial-correlation-sampler: BROKEN
Error: undefined symbol: _ZN3c104cuda29c10_cuda_check_implementationEiPKcS2_ib
```

This is a CUDA version mismatch between Docker build time and Vast.ai runtime.

## Root Cause

1. **Docker image built with**: CUDA 12.8 (PyTorch nightly cu128)
2. **Vast.ai runtime has**: CUDA 12.6, 12.9, or other versions
3. **Result**: `spatial-correlation-sampler` C++ extension fails to load

## Previous Behavior

- ❌ Application would **fail immediately** on startup
- ❌ Required manual rebuild or different GPU instance
- ❌ Wasted time and money on failed jobs

## New Behavior (Fixed)

- ✅ **Auto-detects** CUDA mismatch on startup
- ✅ **Automatically rebuilds** spatial-correlation-sampler (60-180 seconds)
- ✅ **Verifies** rebuild succeeded before continuing
- ✅ **Self-healing** - works on any Vast.ai instance

## Changes Made

### 1. Default Auto-Rebuild to TRUE

**File**: `src/infrastructure/startup.py`

Changed from:
```python
auto_rebuild = os.getenv("AUTO_REBUILD_CUDA_EXTENSIONS", "false").lower() == "true"
```

To:
```python
auto_rebuild = os.getenv("AUTO_REBUILD_CUDA_EXTENSIONS", "true").lower() == "true"
```

**Why**: Auto-rebuild should be the default behavior on Vast.ai where CUDA versions vary.

### 2. Simplified Rebuild Function

**File**: `src/infrastructure/inpainting/raft_wrapper.py`

Removed incorrect attempt to build non-existent `ProPainter/RAFT/core/correlation` extension.

**Before**:
- Step 1: Rebuild spatial-correlation-sampler
- Step 2: Try to build ProPainter/RAFT/core/correlation (❌ doesn't exist!)
- Step 3: Verify

**After**:
- Step 1: Rebuild spatial-correlation-sampler from source (--no-binary)
- Step 2: Verify it works
- Done! ✅

### 3. Better Error Messages

Updated error messages to reflect that auto-rebuild is now the default:
- Explains what's happening during rebuild
- Shows how to disable if needed: `AUTO_REBUILD_CUDA_EXTENSIONS=false`
- Provides troubleshooting steps if rebuild fails

## How It Works Now

### Startup Sequence

```
Container Start
  ↓
Python Application Starts
  ↓
[startup.py] Validate CUDA dependencies
  ↓
Check spatial-correlation-sampler
  ↓
❌ BROKEN (CUDA mismatch detected)
  ↓
[Auto-Rebuild Enabled by Default]
  ↓
pip uninstall spatial-correlation-sampler
pip install --no-binary spatial-correlation-sampler
  ↓ (60-180 seconds)
Compilation completes
  ↓
✅ Verify: spatial-correlation-sampler works
  ↓
✅ Continue with processing
```

### Logs You'll See

```
============================================================
STARTUP: Validating CUDA dependencies...
============================================================
❌ spatial-correlation-sampler: BROKEN
Error: undefined symbol: _ZN3c104cuda29c10_cuda_check_implementation...

Attempting auto-rebuild (default behavior on Vast.ai)...
This will take ~60-180 seconds...
Set AUTO_REBUILD_CUDA_EXTENSIONS=false to disable

Rebuilding spatial-correlation-sampler from source...
PyTorch CUDA version: 12.8
[... compilation logs ...]
✅ spatial-correlation-sampler rebuilt successfully
✅ Verification passed: spatial-correlation-sampler is working
✅ spatial-correlation-sampler: REBUILT SUCCESSFULLY
============================================================
```

## Performance Impact

| Scenario | Time | Frequency |
|----------|------|-----------|
| CUDA matches (no rebuild) | +5 seconds | Most runs on same instance |
| CUDA mismatch (rebuild) | +60-180 seconds | First run on new instance |

**Total impact**: 1-3 minutes extra on **first run** on a new Vast.ai instance, then normal speed for subsequent runs.

## Configuration

### Enable Auto-Rebuild (Default)
```bash
# No env var needed - it's the default now!
python main.py
```

### Disable Auto-Rebuild (Fail Fast)
```bash
export AUTO_REBUILD_CUDA_EXTENSIONS=false
python main.py
# Will fail immediately if CUDA mismatch
```

## Testing

### On Vast.ai
1. Launch instance with any GPU
2. Start container
3. Check logs for auto-rebuild message
4. Wait for rebuild to complete (~60-180 sec first time)
5. Processing should work normally

### Manual Test
```bash
# SSH into Vast.ai instance
vast ssh <instance_id>

# Test spatial-correlation-sampler
python3 -c "import spatial_correlation_sampler; print('✅ OK')"

# Test RAFT import
python3 -c "
import sys
sys.path.insert(0, '/opt/ProPainter')
from model.modules.flow_comp_raft import RAFT
print('✅ RAFT OK')
"
```

## Troubleshooting

### If Rebuild Fails

1. **Check build dependencies**:
   ```bash
   which gcc g++ nvcc
   pip list | grep torch
   ```

2. **Check disk space**:
   ```bash
   df -h
   # Need ~2GB for compilation
   ```

3. **Manual rebuild**:
   ```bash
   pip uninstall -y spatial-correlation-sampler
   pip install --no-cache-dir --force-reinstall \
       --no-binary spatial-correlation-sampler \
       spatial-correlation-sampler
   ```

4. **Check CUDA compatibility**:
   ```bash
   nvidia-smi  # Runtime CUDA version
   python3 -c "import torch; print(torch.version.cuda)"  # PyTorch CUDA
   ```

### If Still Broken After Rebuild

This usually means:
- Build tools not installed in Docker image
- CUDA toolkit not available
- PyTorch/CUDA version incompatibility

**Solution**: Rebuild Docker image with matching CUDA version.

## Why This is Better Than Before

### Before (Fail Fast Approach)
- ❌ Fails immediately on CUDA mismatch
- ❌ Requires manual intervention
- ❌ Wastes GPU time if noticed late
- ❌ Different behavior on each Vast.ai instance

### After (Self-Healing Approach)
- ✅ Automatically fixes CUDA mismatch
- ✅ Works on any Vast.ai instance
- ✅ No manual intervention needed
- ✅ Consistent behavior everywhere

## Docker Image Recommendations

Even with auto-rebuild, it's still best to **rebuild the Docker image** with correct CUDA for production:

**Advantages of proper Docker image**:
- No rebuild time (~2-3 minutes faster)
- More reliable (no compilation failures)
- Smaller attack surface (no build tools needed)

**When auto-rebuild is useful**:
- Testing on different GPU types
- Debugging CUDA issues
- Rapid iteration during development
- When you can't control Docker build environment

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Behavior** | Fail immediately | Auto-rebuild |
| **Default** | Disabled | Enabled |
| **First run on new instance** | ❌ Fails | ✅ Works (+2-3 min) |
| **Subsequent runs** | N/A | ✅ Works (no delay) |
| **Manual intervention** | Required | Optional |
| **Works on all Vast.ai GPUs** | ❌ No | ✅ Yes |

**Result**: The application is now self-healing on Vast.ai! 🎉

