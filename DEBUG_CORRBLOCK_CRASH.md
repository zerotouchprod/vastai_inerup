# 🔍 DEBUG: Diagnose ProPainter Crash

## Status

**Good news**: Validation passes ✅ (no more timeout!)
**Bad news**: ProPainter subprocess still crashes ❌

## Current Error

```
File "/opt/ProPainter/RAFT/raft.py", line 109, in forward
    corr_fn = CorrBlock
```

**Error message is truncated** - we need to see full stderr to understand what's happening.

## Debug Prints Added

Added diagnostic prints to `CorrBlock`:

```python
class CorrBlock:
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, **kwargs):
        print(f"[CorrBlock.__init__] Called with num_levels={num_levels}, radius={radius}, fmap1.shape={fmap1.shape}", file=sys.stderr)
        # ... build pyramid ...
        print(f"[CorrBlock.__init__] Completed successfully, pyramid has {len(self.corr_pyramid)} levels", file=sys.stderr)
    
    def __call__(self, coords):
        print(f"[CorrBlock.__call__] Called with coords.shape={coords.shape}", file=sys.stderr)
        # ... sample correlation ...
```

## How to Run Debug

### Commands:

```bash
# On Vast.ai:
cd ~/vastai_inerup
git pull origin main_rmsubs_roi_ar

# Re-run pipeline with stderr capture
python pipeline_v2.py --input video.mp4 --mode remove-subtitles 2>&1 | tee full_log.txt

# Check for debug prints
grep -E "\[CorrBlock\." full_log.txt

# Or look at job log
tail -f ~/vastai_inerup/job.log
```

### What to Look For:

**Scenario 1: No prints at all**
```
# No [CorrBlock.__init__] lines
```
→ **CorrBlock is not being instantiated** - import problem or wrong module

**Scenario 2: Crash during __init__**
```
[CorrBlock.__init__] Called with num_levels=4, radius=4, fmap1.shape=torch.Size([1, 256, 20, 36])
# Then crash (no "Completed" message)
```
→ **Pyramid building fails** - tensor operation error

**Scenario 3: __init__ succeeds but __call__ never happens**
```
[CorrBlock.__init__] Completed successfully, pyramid has 4 levels
# No [CorrBlock.__call__] message
```
→ **CorrBlock object created but not callable** - API mismatch

**Scenario 4: Crash during __call__**
```
[CorrBlock.__init__] Completed successfully, pyramid has 4 levels
[CorrBlock.__call__] Called with coords.shape=torch.Size([1, 2, 20, 36])
# Then crash
```
→ **Sampling logic fails** - indexing error or shape mismatch

## Expected Debug Output (if working):

```
[CorrBlock.__init__] Called with num_levels=4, radius=4, fmap1.shape=torch.Size([1, 256, 20, 36])
[CorrBlock.__init__] Completed successfully, pyramid has 4 levels
[CorrBlock.__call__] Called with coords.shape=torch.Size([1, 2, 20, 36])
# Process succeeds
```

## Possible Issues to Check

### Issue 1: RAFT line 109

```python
# /opt/ProPainter/RAFT/raft.py, line 109
corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
```

**Problem**: If this line crashes, it means `CorrBlock` import succeeded but instantiation failed.

**Check**: Do we see `[CorrBlock.__init__] Called...`?
- **Yes** → __init__ logic crashes
- **No** → Import returns wrong thing

### Issue 2: Truncated Error Message

The error in job.log is cut off at:
```
File "/opt/ProPainter/RAFT/raft.py", line 109, in forward
    corr_fn = CorrBlock
```

**Need full error** - likely continues with actual exception type.

### Issue 3: coords vs flow

Check if RAFT passes correct arguments:
```python
corr = corr_fn(coords1)  # Does coords1 have right shape?
```

## Next Steps After Running Debug

**Share output with me**:
```bash
# Show first/last 100 lines with CorrBlock mentions
grep -B5 -A5 "\[CorrBlock\." ~/vastai_inerup/job.log | head -100
grep -B5 -A5 "\[CorrBlock\." ~/vastai_inerup/job.log | tail -100
```

**Or full stderr from ProPainter**:
```bash
# Find the actual error (not truncated)
grep -A20 "File \"/opt/ProPainter/RAFT/raft.py\", line 109" ~/vastai_inerup/job.log
```

## Quick Commands

```bash
# Pull debug version
cd ~/vastai_inerup && git pull origin main_rmsubs_roi_ar

# Run with full logging
python pipeline_v2.py --input video.mp4 --mode remove-subtitles 2>&1 | tee /tmp/debug.log

# Check debug output
grep "\[CorrBlock" /tmp/debug.log
```

---

## Summary

**Added**: Debug prints to diagnose crash location
**Need**: Full stderr output to see actual error
**Next**: User runs pipeline and shares debug output

🔍 **Let's find where it crashes!**

