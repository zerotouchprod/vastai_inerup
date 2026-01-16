# ✅ FIXED: ModuleNotFoundError in ProPainter Subprocess

## The Problem

```
File "/opt/ProPainter/RAFT/corr.py", line 15, in <module>
    from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
ModuleNotFoundError: No module named 'src'
```

**ProPainter subprocess couldn't find the project!**

## Root Cause

### Fragile Relative Path

**Old code in corr.py**:
```python
# Tried to guess relative path from RAFT dir:
project_root = Path(__file__).parent.parent.parent.parent / "vastai_inerup"
```

**Problems**:
1. Assumes specific directory structure
2. Doesn't work when subprocess starts from `/opt/ProPainter`
3. No validation that path exists
4. Breaks if project named differently

### Subprocess Working Directory

```
ProPainter subprocess:
  Working dir: /opt/ProPainter
  __file__: /opt/ProPainter/RAFT/corr.py
  
  Relative path calculation:
  parent.parent.parent.parent = /
  / + "vastai_inerup" = /vastai_inerup  ❌ (doesn't exist!)
```

## The Fix: Absolute Path Discovery

### Try Multiple Standard Locations

```python
possible_roots = [
    Path("/root/vastai_inerup"),      # Vast.ai standard
    Path("/workspace/project"),       # Docker standard  
    Path.home() / "vastai_inerup",    # User home
]

for root in possible_roots:
    check_file = root / "src" / "infrastructure" / "inpainting" / "pure_pytorch_correlation.py"
    if root.exists() and check_file.exists():
        project_root = root  # ✅ Found it!
        break
```

### Why This Works

| Aspect | Old (Relative) | New (Absolute) |
|--------|----------------|----------------|
| Paths | Relative from RAFT dir | Absolute known locations |
| Validation | None | Checks file exists |
| Subprocess | ❌ Breaks | ✅ Works |
| Clarity | Fragile guessing | Clear standard paths |

## How to Apply Fix

### On Running Instance (Quick Fix)

```bash
# SSH to your Vast.ai instance
ssh root@your-instance

# Pull latest code
cd ~/vastai_inerup
git pull origin main_rmsubs_roi_ar

# Run update script
bash scripts/update_corrpy.sh

# Re-run pipeline
python pipeline_v2.py --input video.mp4 --mode remove-subtitles
```

### What update_corrpy.sh Does

1. **Overwrites** `/opt/ProPainter/RAFT/corr.py` with new version
2. **Tests** import works
3. **Confirms** Pure PyTorch CorrBlock accessible

### Expected Output

```
🔧 Updating /opt/ProPainter/RAFT/corr.py...
✅ Updated /opt/ProPainter/RAFT/corr.py

🧪 Testing import...
✅ Import successful!
   CorrBlock: <class 'CorrBlock'>
   AlternateCorrBlock: <class 'CorrBlock'>

🎉 corr.py updated and tested successfully!
```

## Verification

### Test Import Manually

```bash
# Test from ProPainter's perspective:
cd /opt/ProPainter
python3 -c "
from RAFT.corr import CorrBlock, AlternateCorrBlock
print('✅ Success!')
"
```

Should print: `✅ Success!`

### Check Project Found

```bash
python3 << 'EOF'
from pathlib import Path

possible_roots = [
    Path("/root/vastai_inerup"),
    Path("/workspace/project"),
    Path.home() / "vastai_inerup",
]

for root in possible_roots:
    check = root / "src/infrastructure/inpainting/pure_pytorch_correlation.py"
    if root.exists() and check.exists():
        print(f"✅ Project found at: {root}")
        break
else:
    print("❌ Project NOT found in standard locations!")
EOF
```

Expected: `✅ Project found at: /root/vastai_inerup`

## Technical Details

### Path Resolution Flow

```
Subprocess imports: from RAFT.corr import CorrBlock
  ↓
corr.py executes:
  ↓
Check /root/vastai_inerup
  → src/infrastructure/inpainting/pure_pytorch_correlation.py exists? ✅
  ↓
Set project_root = Path("/root/vastai_inerup")
  ↓
sys.path.insert(0, "/root/vastai_inerup")
  ↓
from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock ✅
  ↓
Success!
```

### Standard Locations Explained

**Vast.ai**: `/root/vastai_inerup`
- When you `git clone` as root user
- Standard Vast.ai setup

**Docker**: `/workspace/project`
- Many Docker images mount code here
- Clean separation from system

**User Home**: `~/vastai_inerup`
- Local development
- Multi-user systems

### Error Messages

If project not found:
```python
raise ImportError(
    "Cannot find vastai_inerup project!\n"
    f"Tried: {[str(p) for p in possible_roots]}\n"
    "Ensure project at /root/vastai_inerup or /workspace/project"
)
```

Clear, actionable error! ✅

## Files Changed

### 1. docker/patches/raft_corr.py
Source template with robust path finding

### 2. src/application/factories.py
Inline version in `_inject_pure_pytorch_corrblock()` updated

### 3. scripts/update_corrpy.sh (NEW!)
Quick fix script for running instances

## Migration

### For Existing Instances

Run update script once:
```bash
cd ~/vastai_inerup
git pull
bash scripts/update_corrpy.sh
```

### For New Instances

Automatic! Code will inject updated corr.py with robust path finding.

## Summary

**Problem**: Fragile relative path couldn't find project from subprocess
**Solution**: Try absolute standard locations with validation
**Result**: Subprocess finds project reliably! ✅

**Architecture**: 
- Absolute paths (not relative)
- Multiple fallbacks (not single guess)
- Validation (not blind trust)
- Clear errors (not cryptic failures)

**Senior approach**: Handle real-world deployment variations! 🎯

---

## Quick Commands

```bash
# Pull fix
cd ~/vastai_inerup && git pull origin main_rmsubs_roi_ar

# Apply to running instance
bash scripts/update_corrpy.sh

# Test it works
cd /opt/ProPainter && python3 -c "from RAFT.corr import CorrBlock; print('✅')"

# Run pipeline
python pipeline_v2.py --input video.mp4 --mode remove-subtitles
```

**Now subprocess will find Pure PyTorch CorrBlock!** 🚀

