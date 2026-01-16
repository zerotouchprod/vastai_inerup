# 🚨 CRITICAL FIX APPLIED: corr.py Updates Now Work!

## Problem Found

**Debug prints didn't appear** → corr.py wasn't being updated!

### Root Cause

`factories.py` had this code:
```python
# 4. Check if already injected
if corr_py_dest.exists():
    content = corr_py_dest.read_text()
    if "Pure PyTorch CorrBlock" in content:
        self._logger.info("✅ Pure PyTorch corr.py already installed")
        return  # ❌ EXITS WITHOUT UPDATING!
```

**This blocked all updates!**
- First run: installs corr.py (old version without debug)
- Second run: sees "Pure PyTorch" in file → exits
- Debug version never applied ❌

## Solution

**Removed early return** - now ALWAYS overwrites:
```python
# 3. Backup original (once)
if not corr.py.original exists:
    backup original

# 4. ALWAYS overwrite to ensure latest version
# (no early return!)
copy new version → /opt/ProPainter/RAFT/corr.py
```

## For User

### Commands:

```bash
# On Vast.ai:
cd ~/vastai_inerup
git pull origin main_rmsubs_roi_ar

# Re-run pipeline (will now update corr.py)
python pipeline_v2.py --input video.mp4 --mode remove-subtitles 2>&1 | tee /tmp/debug.log

# Check for debug prints
grep "\[CorrBlock" /tmp/debug.log
```

### Expected Output (NOW):

```
✅ Injected Pure PyTorch CorrBlock into ProPainter RAFT (file-based)
   Created: /opt/ProPainter/RAFT/corr.py
   
# During ProPainter execution:
[CorrBlock.__init__] Called with num_levels=4, radius=4, fmap1.shape=torch.Size([...])
[CorrBlock.__init__] Completed successfully, pyramid has 4 levels
[CorrBlock.__call__] Called with coords.shape=torch.Size([...])
```

**This will show**:
- ✅ Is CorrBlock instantiated?
- ✅ What parameters it receives?
- ✅ Does pyramid build successfully?
- ✅ Is __call__ invoked?
- ✅ **Where exactly does it crash?**

## What Changed

| Before | After |
|--------|-------|
| Check if exists → skip update | Always overwrite with latest |
| Debug prints never applied | Debug prints apply immediately |
| No visibility into crash | Full debug output |

## Impact

**This fix enables**:
- ✅ Debug prints will appear
- ✅ Future updates apply automatically
- ✅ No need to manually delete corr.py
- ✅ Latest version always used

## Verification

After running pipeline, check that corr.py was updated:
```bash
# On Vast.ai:
cat /opt/ProPainter/RAFT/corr.py | head -20
```

**Should see**:
```python
#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module - SELF-CONTAINED
...
"""
import torch
import torch.nn.functional as F

class CorrBlock:
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, **kwargs):
        import sys
        print(f"[CorrBlock.__init__] Called with num_levels={num_levels}...", file=sys.stderr, flush=True)
        # ^^^ Debug print present!
```

## Why This Matters

**Without this fix**:
- Updates never apply
- Stuck with old code
- No way to debug

**With this fix**:
- Every run uses latest code
- Debug prints appear
- Can diagnose crash
- Can fix actual issue

---

## Quick Test

```bash
cd ~/vastai_inerup && git pull origin main_rmsubs_roi_ar
python pipeline_v2.py --input video.mp4 --mode remove-subtitles 2>&1 | grep "\[CorrBlock"
```

**Expected**: See `[CorrBlock.__init__]` and `[CorrBlock.__call__]` lines!

🎯 **NOW WE'LL SEE WHAT'S ACTUALLY HAPPENING!**

