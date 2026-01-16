# ✅ FIXED: ProPainter Subprocess Import Issue

## The Problem

```
[10:48:28] ✅ CorrBlock validation passed: ProPainter will use Pure PyTorch
...
[10:49:17] ERROR: cannot import name 'AlternateCorrBlock' from '<unknown module name>'
```

**Validation passed in main process, but subprocess failed!**

## Root Cause

### sys.modules Injection Doesn't Work for Subprocess

**What we did (WRONG for subprocess)**:
```python
# In main Python process:
sys.modules['RAFT.corr'] = FakeCorrModule(CorrBlock=PurePytorchCorrBlock)
```

**ProPainter runs in subprocess**:
```python
# ProPainterAdapter._run_inference_subprocess():
subprocess.run(['python3', '/opt/ProPainter/inference_propainter.py', ...])
```

### The Issue

```
Main Process                     Subprocess (NEW Python)
=============                    =======================
sys.modules['RAFT.corr'] = ...  sys.modules = {}  (clean!)
  ↓                                ↓
Validation passes ✅               from RAFT.corr import CorrBlock
                                   ❌ ModuleNotFoundError!
```

**Each Python process has separate `sys.modules`!**

## The Fix: File-Based Injection

### Instead of Memory (sys.modules)

Create actual file on disk:
```
/opt/ProPainter/RAFT/corr.py  ← Subprocess can import this!
```

### Implementation

```python
def _inject_pure_pytorch_corrblock(self):
    """Create /opt/ProPainter/RAFT/corr.py with Pure PyTorch CorrBlock."""
    corr_py_content = '''
from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
AlternateCorrBlock = CorrBlock  # Alias
__all__ = ['CorrBlock', 'AlternateCorrBlock']
'''
    Path("/opt/ProPainter/RAFT/corr.py").write_text(corr_py_content)
```

### Why It Works

```
Main Process                     Subprocess
=============                    ===========
Creates file: corr.py ✅         from RAFT.corr import CorrBlock
                                 ↓
                                 Reads file: corr.py ✅
                                 ↓
                                 Gets Pure PyTorch CorrBlock ✅
```

**Files are shared across all processes!**

## Comparison

| Approach | Main Process | Subprocess | Persistence |
|----------|--------------|------------|-------------|
| **sys.modules** | ✅ Works | ❌ Doesn't work | Memory only |
| **File-based** | ✅ Works | ✅ Works | Disk (persistent) |

## Updated Flow

### Before (Broken)
```
create_subtitle_remover():
  1. Inject: sys.modules['RAFT.corr'] = FakeCorrModule()
  2. Validate: import RAFT.corr ✅ (works in main process)
  3. ProPainter subprocess:
     python3 inference_propainter.py
     → from RAFT.corr import CorrBlock
     → ❌ FAIL (subprocess has clean sys.modules)
```

### After (Fixed)
```
create_subtitle_remover():
  1. Inject: copy corr.py → /opt/ProPainter/RAFT/corr.py
  2. Validate: subprocess test import ✅
  3. ProPainter subprocess:
     python3 inference_propainter.py
     → from RAFT.corr import CorrBlock
     → Reads corr.py from disk ✅
     → Gets Pure PyTorch CorrBlock ✅
```

## Technical Details

### AlternateCorrBlock

ProPainter imports **two** names:
```python
from .corr import CorrBlock, AlternateCorrBlock
```

Our file provides both:
```python
# /opt/ProPainter/RAFT/corr.py
CorrBlock = PurePytorchCorrBlock
AlternateCorrBlock = CorrBlock  # Alias for same class
```

### Path Resolution

Subprocess needs to import from our code:
```python
# corr.py needs to import Pure PyTorch:
import sys
sys.path.insert(0, '/root/vastai_inerup')  # Add our project
from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
```

### Validation in Subprocess

**Critical**: Test import in **subprocess**, not main process!

```python
# Simulate what ProPainter does:
test_code = """
import sys
sys.path.insert(0, '/opt/ProPainter')
sys.path.insert(0, '/root/vastai_inerup')
from RAFT.corr import CorrBlock, AlternateCorrBlock
print('SUCCESS')
"""
result = subprocess.run([sys.executable, '-c', test_code], ...)
assert 'SUCCESS' in result.stdout
```

## Architecture Benefits

### 1. **Standard Python**
- File-based imports are normal Python
- No magic sys.modules manipulation
- Easy to understand

### 2. **Works for All Processes**
- Main process ✅
- Subprocess ✅
- Future processes ✅

### 3. **Debuggable**
- Can inspect file: `cat /opt/ProPainter/RAFT/corr.py`
- Can test manually: `python3 -c "from RAFT.corr import CorrBlock"`
- Clear what's happening

### 4. **Reversible**
- Original backed up: `corr.py.original`
- Can restore: `mv corr.py.original corr.py`
- Clean rollback

### 5. **Maintainable**
- Clear intent: file replaces module
- Easy to modify: just edit file
- No runtime magic

## Why sys.modules Failed

### Process Isolation

```python
# Process 1 (main):
import sys
sys.modules['X'] = MyModule()

# Process 2 (subprocess):
import sys
print(sys.modules.get('X'))  # None! Different process!
```

**Each process has separate memory!**

### subprocess.run() Creates New Process

```python
subprocess.run(['python3', 'script.py'])
# ↓
# Spawns NEW Python interpreter
# Clean sys.modules
# No knowledge of parent's sys.modules
```

## Lessons Learned

### ❌ Don't Use sys.modules for Subprocess

If code runs in subprocess:
- sys.modules won't work
- Need file-based or environment-based approach

### ✅ Use Files for Cross-Process

Files are shared:
- Main process writes file
- Subprocess reads file
- Works reliably

### ✅ Validate in Target Environment

Don't just test in main process:
- Test in subprocess
- Simulate actual usage
- Catch issues early

## Summary

**Problem**: sys.modules injection doesn't work for subprocess
**Root cause**: Each Python process has separate sys.modules
**Solution**: File-based injection (/opt/ProPainter/RAFT/corr.py)
**Result**: Subprocess can import Pure PyTorch CorrBlock! ✅

**Architecture**: Clean, standard Python file import (not memory hack)

---

## Quick Check

Verify it works:

```bash
# Check file exists
ls -la /opt/ProPainter/RAFT/corr.py

# Test import (simulates subprocess)
python3 -c "
import sys
sys.path.insert(0, '/opt/ProPainter')
sys.path.insert(0, '/root/vastai_inerup')
from RAFT.corr import CorrBlock, AlternateCorrBlock
print('✅ SUCCESS')
"
```

Expected: `✅ SUCCESS`

**Now ProPainter subprocess works!** 🎉

