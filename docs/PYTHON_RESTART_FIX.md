# CUDA Extension Rebuild - Python Memory Issue FIXED

## The Problem You Hit

После rebuild spatial-correlation-sampler, verification все равно fails:
```
✅ Compilation successful
❌ Verification failed: spatial-correlation-sampler not installed: 
   undefined symbol: _ZN3c104cuda29c10_cuda_check_implementation...
```

## Why This Happens

**Python уже загрузил старый `.so` file в память!**

1. Python импортировал `spatial_correlation_sampler` при первой проверке
2. Старый `.so` файл загружен в память процесса
3. Rebuild создал новый `.so` файл на диске
4. Но Python **не перезагружает** модуль автоматически
5. Verification использует старый модуль из памяти → fails

Это нормальное поведение Python - модули загружаются один раз.

## The Fix

### Solution 1: Auto-Restart (Recommended) ✅

После успешного rebuild, Python процесс **автоматически exits** с кодом 42:
```python
logger.warning("⚠️  Python process must RESTART to use new extension")
logger.warning("   Exiting now to force restart...")
sys.exit(42)  # Special code: rebuild succeeded, restart needed
```

**Если у вас есть supervisor/wrapper**, он увидит exit code 42 и перезапустит процесс.

### Solution 2: Manual Restart

После rebuild просто перезапустите команду:
```bash
# First run - rebuild happens, exits with code 42
python pipeline_v2.py --input video.mp4
# Exit code: 42

# Second run - extension already rebuilt, works!
python pipeline_v2.py --input video.mp4
# Exit code: 0 ✅
```

### Solution 3: Auto-Restart Wrapper (Automated)

Используйте wrapper script для автоматического перезапуска:
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

Wrapper автоматически:
1. Запускает pipeline_v2.py
2. Если exit code = 42 → перезапускает
3. Если exit code = 0 → завершает успешно
4. Макс 3 перезапуска (защита от loop)

## Updated Flow

### With Auto-Restart

```
[Container starts]
  ↓
[Run: python auto_restart_wrapper.py python pipeline_v2.py]
  ↓
[Check spatial-correlation-sampler]
  ↓
❌ BROKEN (CUDA mismatch)
  ↓
[Auto-rebuild - 60-180 seconds]
  ↓
✅ Compilation successful
  ↓
⚠️  Exit with code 42 (restart needed)
  ↓
[Wrapper detects exit 42]
  ↓
🔄 Auto-restart in 2 seconds...
  ↓
[Check spatial-correlation-sampler]
  ↓
✅ Works! (new extension loaded)
  ↓
✅ Processing continues
```

### Without Wrapper (Manual)

```
First run:
  ❌ BROKEN → Rebuild → Exit 42

Second run:
  ✅ Works → Processing completes
```

## New Log Output

### First Run (Rebuild)
```
[09:56:30] ❌ spatial-correlation-sampler: BROKEN
[09:56:30] Attempting auto-rebuild...

[09:56:30] 🔧 Starting CUDA extension rebuild...
[09:56:30] Step 1/3: Uninstalling old version...
[09:56:31] ✅ Old version uninstalled

[09:56:31] Step 2/3: Compiling CUDA extension from source...
⏳ This is the longest step - please be patient...

[09:58:45] ⏱️  Compilation took 134.2 seconds
[09:58:45] ✅ Compilation successful

[09:58:45] Step 3/3: Extension rebuilt successfully

================================================================================
[09:58:45] ✅ REBUILD COMPLETE in 136.5 seconds
================================================================================

⚠️  IMPORTANT: Python process must RESTART to use new extension
   The current Python process has old .so file in memory
   Exiting now to force restart...

[Process exits with code 42]
```

### Second Run (After Restart)
```
[10:00:00] STARTUP: Validating CUDA dependencies...
[10:00:00] Checking spatial-correlation-sampler...
[10:00:00] ✅ spatial-correlation-sampler: OK
============================================================
✅ ALL STARTUP CHECKS PASSED
============================================================

[Processing continues normally...]
```

## Configuration

### Use Auto-Restart Wrapper

Update your command to use wrapper:

**Before:**
```bash
python pipeline_v2.py --input video.mp4
```

**After:**
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

### Or Handle Exit Code 42

In your deployment script:
```bash
#!/bin/bash
while true; do
    python pipeline_v2.py "$@"
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 42 ]; then
        echo "CUDA rebuild succeeded, restarting..."
        sleep 2
        continue
    fi
    
    # Any other exit code - stop
    exit $EXIT_CODE
done
```

## Why This Is Better

### Before (Broken)
- ✅ Rebuild succeeded
- ❌ Verification fails (old .so in memory)
- ❌ Application crashes
- ❌ User confused

### After (Fixed)
- ✅ Rebuild succeeded
- ⚠️ Clear message: restart needed
- 🔄 Automatic restart (exit 42)
- ✅ Second run works
- ✅ User happy

## Technical Details

### Why Can't We Force Reload?

Python загружает C extensions в память процесса напрямую через `dlopen()`. После загрузки:
- Нельзя "unload" без сегфолтов
- `importlib.reload()` не работает для C extensions
- `sys.modules.clear()` опасен

**Единственный safe способ** - restart Python process.

### Why Exit Code 42?

- Standard exit codes: 0 = success, 1 = error
- Custom exit codes allowed: 1-255
- 42 = "The Answer to Life, Universe, and Everything" (Douglas Adams)
- Also unique enough to not conflict with other codes
- Easy to remember and detect

### Why 2 Second Wait?

Дает время:
- Файловой системе закончить запись
- Логам flush
- Пользователю увидеть сообщение

## Files Changed

✅ `src/infrastructure/inpainting/raft_wrapper.py`
- After successful rebuild: `sys.exit(42)` instead of verification
- Clear warning messages about restart requirement

✅ `auto_restart_wrapper.py` (NEW)
- Wraps application
- Detects exit code 42
- Automatically restarts
- Max 3 attempts

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Rebuild** | ✅ Succeeds | ✅ Succeeds |
| **Verification** | ❌ Fails (old .so) | ⚠️ Skipped (needs restart) |
| **User action** | Manual debug | Auto-restart or manual |
| **Second run** | N/A | ✅ Works perfectly |
| **Exit code** | 1 (error) | 42 (restart needed) |
| **User confusion** | High 😰 | Low 😊 |

## Quick Start

### Option 1: Auto-Restart Wrapper (Easiest)
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

### Option 2: Manual Restart
```bash
# First run
python pipeline_v2.py --input video.mp4
# If exits with 42, run again:
python pipeline_v2.py --input video.mp4
```

### Option 3: Shell Loop
```bash
while python pipeline_v2.py "$@"; [ $? -eq 42 ]; do
    echo "Restarting after CUDA rebuild..."
    sleep 2
done
```

---

## 🎉 Result

**CUDA extension rebuild теперь работает полностью!**

После rebuild Python process автоматически restarts (или вы видите четкую инструкцию), и на втором запуске все работает идеально! ✅

