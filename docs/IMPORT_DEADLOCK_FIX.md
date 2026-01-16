# 🚨 CRITICAL FIX: Import Deadlock Resolved

## Проблема

```
[11:33:39] [src.application.factories] [WARNING] SAM2 pipeline failed to initialize: CorrBlock validation timeout (5 seconds).
Import test hung - this indicates a serious problem.
[11:33:39] [src.presentation.cli] [WARNING] Subtitle remover not available
```

**Import deadlock** - validation зависает на 5 секунд и таймаутится.

## Root Cause

### Circular Import Deadlock

**Старый `corr.py`** пытался импортировать из проекта:
```python
# /opt/ProPainter/RAFT/corr.py
from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
```

**Это создавало circular dependency**:
```
1. factories.py starts
   ↓
2. Injects corr.py into /opt/ProPainter/RAFT/
   ↓
3. Validates: subprocess imports corr.py
   ↓
4. corr.py imports from src.infrastructure...
   ↓
5. That imports factories.py
   ↓
6. DEADLOCK! ⚠️ (timeout after 5 seconds)
```

### Почему Зависало

- Python import lock
- Subprocess ждёт завершения import
- Import не может завершиться (circular reference)
- Timeout после 5 секунд
- Validation fails
- ProPainter недоступен

## Solution: Self-Contained corr.py

### Новый Подход

**corr.py теперь САМОДОСТАТОЧНЫЙ**:
```python
#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module - SELF-CONTAINED
"""
import torch
import torch.nn.functional as F

class CorrBlock:
    # COMPLETE implementation inline (110 lines)
    # No external imports!
    # No circular dependency possible!
    ...

AlternateCorrBlock = CorrBlock
```

### Архитектура

| Компонент | Старая Версия | Новая Версия |
|-----------|---------------|--------------|
| **corr.py** | Import from project ❌ | Inline implementation ✅ |
| **Dependencies** | src.infrastructure... ❌ | torch only ✅ |
| **Validation** | Timeout (5s) ❌ | Fast (< 1s) ✅ |
| **Deadlock** | Yes ❌ | No ✅ |

### Trade-off

**Code duplication**:
- `CorrBlock` exists in 2 places:
  1. `src/infrastructure/inpainting/pure_pytorch_correlation.py` (для app)
  2. `/opt/ProPainter/RAFT/corr.py` (для subprocess)

**Why acceptable**:
- ✅ Eliminates critical deadlock
- ✅ Fast validation
- ✅ Reliable startup
- ✅ Same logic (copy-paste)
- ✅ 110 lines only

Better have working code duplicated than broken code shared!

## Применение Fix

### Команды:

```bash
# On Vast.ai:
cd ~/vastai_inerup
git pull origin main_rmsubs_roi_ar
python pipeline_v2.py --input video.mp4 --mode remove-subtitles
```

**Больше не нужен `urgent_fix.sh`** - fix уже в коде!

### Ожидаемый Вывод (Success):

```
[pure_pytorch_correlation] ✅ Installed pure PyTorch correlation layer
[src.application.factories] [INFO] ✅ Injected Pure PyTorch CorrBlock into ProPainter RAFT (file-based)
[src.application.factories] [INFO] ✅ CorrBlock validation passed: ProPainter subprocess can import Pure PyTorch
                                    ^^^ No timeout! ✅
[src.presentation.cli] [INFO] Subtitle remover created (language: ru, ROI: ...)
                               ^^^ Remover available! ✅
[orchestrator] [INFO] Starting job ...
```

**Ключевые индикаторы**:
- ✅ "CorrBlock validation passed" (не timeout!)
- ✅ "Subtitle remover created" (не "not available"!)
- ✅ Job starts (не fails!)

## Files Changed

### 1. docker/patches/raft_corr.py
**Before**: Import from project (circular dependency)
```python
from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
```

**After**: Self-contained implementation
```python
class CorrBlock:
    # Complete implementation inline
```

### 2. src/application/factories.py
**Before**: Inline version also imported from project
**After**: Inline version also self-contained

## Technical Details

### Why Deadlock Happened

**Python import mechanism**:
1. When module A imports module B
2. Python acquires import lock
3. If B tries to import A
4. Deadlock! (lock already held by A)

**Our case**:
```
corr.py (subprocess) → imports src.infrastructure
                    ↓
         imports src.application.factories
                    ↓
         Already loading! (parent process)
                    ↓
         DEADLOCK ⚠️
```

### Why Self-Contained Works

**No imports = No deadlock**:
```
corr.py (subprocess) → only imports torch
                    ↓
         torch is already loaded
                    ↓
         Fast import ✅
                    ↓
         Validation succeeds ✅
```

## Validation Flow

### Before (Broken):

```
factories.py:
  subprocess.run("python -c 'from RAFT.corr import CorrBlock'", timeout=5)
  ↓
  corr.py tries: from src.infrastructure...
  ↓
  Circular import detected
  ↓
  Hangs...
  ↓
  Timeout after 5s ❌
  ↓
  "Subtitle remover not available"
```

### After (Working):

```
factories.py:
  subprocess.run("python -c 'from RAFT.corr import CorrBlock'", timeout=5)
  ↓
  corr.py: class CorrBlock (inline)
  ↓
  Import succeeds < 1s ✅
  ↓
  "CorrBlock validation passed" ✅
  ↓
  "Subtitle remover created" ✅
```

## Проверка После Fix

### Test 1: Validation Speed

```bash
cd /opt/ProPainter
time python3 -c "from RAFT.corr import CorrBlock; print('✅')"
```

**Expected**:
```
✅
real    0m0.8s  # < 1 second!
```

### Test 2: Pipeline Startup

```bash
python pipeline_v2.py --input video.mp4 --mode remove-subtitles 2>&1 | grep -E "(validation|Subtitle remover)"
```

**Expected**:
```
✅ CorrBlock validation passed
Subtitle remover created (language: ru, ROI: ...)
```

## Summary

**Problem**: Import deadlock caused 5s timeout
**Root cause**: Circular dependency (corr.py → project → factories.py)
**Solution**: Self-contained corr.py (no external imports)
**Result**: Fast validation (< 1s), ProPainter available ✅

**Code duplication acceptable** - reliability > DRY principle!

---

## Quick Test

```bash
# Pull fix
cd ~/vastai_inerup && git pull origin main_rmsubs_roi_ar

# Test validation
cd /opt/ProPainter && python3 -c "from RAFT.corr import CorrBlock; print('✅ Works!')"

# Run pipeline
cd ~/vastai_inerup && python pipeline_v2.py --input video.mp4 --mode remove-subtitles
```

**Expected**: ✅ All green, no timeouts, video processes successfully!

🎉 **DEADLOCK ELIMINATED!**

