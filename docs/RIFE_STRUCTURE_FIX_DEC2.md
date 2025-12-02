# 🔧 RIFE Repository Structure Fix (Dec 2, 2025)

## Problem

The RIFE processing was failing with this error:

```
[08:30:44] [RIFENativeWrapper] [ERROR] Native RIFE processing failed: RIFE_HDv3.py not found. 
Searched: ['/workspace/project/external/RIFE', 'external/RIFE', '/workspace/project/external/RIFE']
```

### Root Cause

The RIFE GitHub repository structure changed in recent commits. The latest `main` branch has moved `RIFE_HDv3.py` and related model files from the root directory into the `model/` subdirectory.

**Old Structure (what our code expects):**
```
RIFE/
├── RIFE_HDv3.py          ← Expected here
├── IFNet_HDv3.py         ← Expected here
├── warplayer.py          ← Expected here
├── train_log/
│   └── *.pkl files
└── ...
```

**New Structure (current main branch):**
```
RIFE/
├── model/
│   ├── RIFE_HDv3.py      ← Now here
│   ├── IFNet_HDv3.py     ← Now here
│   └── warplayer.py      ← Now here
├── train_log/
└── ...
```

## Solution

Updated `scripts/remote_runner.sh` to:

1. **Clone from v4.6 tag** instead of `main` branch
   - Tag v4.6 has the correct structure or files can be easily located
   
2. **Copy files from model/ to root** for backward compatibility
   - After clone, copy `RIFE_HDv3.py`, `IFNet_HDv3.py`, and `warplayer.py` from `model/` to root
   - This ensures our existing code (which looks in root) continues to work

### Changes Made

**File:** `scripts/remote_runner.sh`

**Before:**
```bash
git clone --depth 1 https://github.com/hzwer/RIFE.git /workspace/project/external/RIFE
```

**After:**
```bash
git clone --depth 1 --branch v4.6 https://github.com/hzwer/RIFE.git /workspace/project/external/RIFE

# Copy RIFE_HDv3.py and IFNet_HDv3.py from model/ to root for compatibility
if [ -f "/workspace/project/external/RIFE/model/RIFE_HDv3.py" ]; then
  cp /workspace/project/external/RIFE/model/RIFE_HDv3.py /workspace/project/external/RIFE/
  cp /workspace/project/external/RIFE/model/IFNet_HDv3.py /workspace/project/external/RIFE/ 2>/dev/null || true
  cp /workspace/project/external/RIFE/model/warplayer.py /workspace/project/external/RIFE/ 2>/dev/null || true
  echo "[remote_runner] Copied RIFE model files to root directory"
fi
```

This change was applied in **TWO locations**:
1. Initial RIFE clone (when directory doesn't exist)
2. Re-clone (when directory exists but `RIFE_HDv3.py` is missing)

## Monitor Improvements

Also updated `monitor.py` to show more logs:

1. **Increased default tail from 200 to 1000 lines**
   - Previous: `--tail 200` (default)
   - New: `--tail 1000` (default)

2. **Added `--full` flag** to show ALL logs on first check
   - Usage: `python monitor.py <instance_id> --full`
   - Shows complete log history instead of just last 100 lines

3. **Better initial log display**
   - First check: Shows last 100 lines (or all if --full)
   - Subsequent checks: Shows last 20 new lines

### Usage Examples

```bash
# Monitor with default settings (1000 lines tail)
python monitor.py 28421359

# Show ALL logs on startup
python monitor.py 28421359 --full

# Custom tail and interval
python monitor.py 28421359 --tail 2000 --interval 3
```

## Testing

After pushing these changes:

1. **Destroy** current instance (has old code):
   ```bash
   python monitor.py 28421359 --destroy
   ```

2. **Start new instance** (will pull updated code):
   ```bash
   python batch_processor.py
   ```

3. **Monitor with full logs**:
   ```bash
   python monitor.py <new_instance_id> --full
   ```

## Expected Result

After restarting with updated code, you should see:

```
[remote_runner] Checking external/RIFE...
[remote_runner] Cloning RIFE...
[remote_runner] Copied RIFE model files to root directory
[remote_runner] ✓ RIFE_HDv3.py confirmed present
```

And the processing should complete successfully without the `RIFE_HDv3.py not found` error.

## Alternative Solution (Future)

For a more permanent fix, we could update `src/infrastructure/processors/rife/native.py` to look for files in multiple locations:

```python
rife_src_paths = [
    Path('/workspace/project/external/RIFE'),
    Path('/workspace/project/external/RIFE/model'),  # NEW
    Path('external/RIFE'),
    Path('external/RIFE/model'),  # NEW
    # ...
]
```

But the current solution (copying files) is simpler and maintains backward compatibility.

## Commit Info

- **Files Changed:** `scripts/remote_runner.sh`, `monitor.py`
- **Purpose:** Fix RIFE repo structure incompatibility + improve log monitoring
- **Date:** December 2, 2025

