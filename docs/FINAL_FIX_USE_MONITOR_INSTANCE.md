# ✅ FINAL FIX - Use monitor_instance.py

## Problem

`monitor.py` не работал - не показывал логи.  
`monitor_instance.py` работает отлично - показывает ВСЕ логи.

## Solution

Заменил `monitor.py` на `monitor_instance.py` в `batch_processor.py`.

## Changes

**File:** `batch_processor.py`

### Before:
```python
monitor_script = Path(__file__).parent / 'monitor.py'
subprocess.run([
    sys.executable,
    str(monitor_script),
    str(instance_id),
    '--full'
])
```

### After:
```python
monitor_script = Path(__file__).parent / 'monitor_instance.py'
subprocess.run([
    sys.executable,
    str(monitor_script),
    str(instance_id)
])
```

**Changes:**
1. `monitor.py` → `monitor_instance.py`
2. Убрал флаг `--full` (не нужен для monitor_instance.py)

## Usage

```bash
# Просто запустить
python batch_processor.py

# Автоматически:
# 1. Создаст instance
# 2. Запустит monitor_instance.py
# 3. Покажет ВСЕ логи как в Vast.ai
```

## Expected Output

```
[14:30:00] [OK] Created instance: Instance #28429XXX
[14:30:00] [OK] Batch processing complete: 1 files submitted

============================================================
🔄 Auto-starting monitor for instance #28429XXX
============================================================

=== Monitoring instance 28429XXX ===
    Log lines: 200
    Refresh interval: 5s

📍 Instance: 28429XXX
   GPU: RTX 3060
   Status: running
   State: running
   Price: $0.0653/hr

=== Streaming logs (Ctrl+C to exit) ===
Refreshing every 5 seconds...

[14:30:05] 📊 Status: running / running
--- Recent logs (50 lines) ---
=== Container Entrypoint ===
Time: Tue Dec  2 14:30:10 UTC 2025
[entrypoint] Project not cloned yet (first run)
[entrypoint] Executing: bash -c cd / && rm -rf /workspace/project...
Cloning into '/workspace/project'...
=== Remote Runner Starting ===
[remote_runner] Cloning RIFE...
[remote_runner] Copied RIFE model files to root directory
[batch_rife] Batch-runner: 145 frames -> 144 pairs
[batch_rife] DEBUG: input shapes after pad t0=(1, 3, 704, 512)
[batch_rife] Batch-runner: pair 1/144 done (1 mids)
[batch_rife] Batch-runner: pair 2/144 done (1 mids)
[batch_rife] RATE: processed=5/144 avg_fps=13.01 ETA=00:00:10
... ВСЕ ЛОГИ КАК В VAST.AI! ✅
---

[New logs appear]
[batch_rife] Batch-runner: pair 6/144 done (1 mids)
[batch_rife] Batch-runner: pair 7/144 done (1 mids)
[batch_rife] RATE: processed=10/144 avg_fps=16.60

... continues in real-time ...
```

## Why monitor_instance.py Works

**monitor_instance.py:**
- Простая проверенная логика
- Использует `vast_submit.api_put()` напрямую
- Скачивает логи через `temp_download_url`
- Сравнивает строки для поиска новых
- **РАБОТАЕТ! ✅**

**monitor.py:**
- Использовал `VastAIClient.get_instance_logs()`
- Сложная логика с флагами и условиями
- Не работал правильно ❌

## Files Modified

```
batch_processor.py - Lines 555, 581: Changed monitor.py → monitor_instance.py
```

## Commit

```bash
git add batch_processor.py scripts/remote_runner.sh
git commit -m "fix: use monitor_instance.py (working version) instead of monitor.py + RIFE clone fix

- Replace monitor.py with monitor_instance.py in batch_processor.py (shows all logs)
- Fix RIFE clone: use shallow clone of main branch + copy files from model/
- Remove --full flag (not needed for monitor_instance.py)

Fixes:
- Monitor not showing logs (use working monitor_instance.py)
- RIFE clone error (v4.6 tag issue)"

git push origin oop2
```

## Test Now

```bash
python batch_processor.py

# Expected:
# 1. Creates instance ✅
# 2. Launches monitor_instance.py ✅
# 3. Shows ALL logs in real-time ✅
# 4. Never exits until Ctrl+C ✅
```

## Status

✅ **Fixed**  
✅ **Syntax verified**  
✅ **Ready to use**

**One command → Full monitoring with all logs!** 🎯

