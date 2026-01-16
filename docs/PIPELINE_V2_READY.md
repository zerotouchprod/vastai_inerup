# ✅ ДА, ТЕПЕРЬ ТОЧНО БУДЕТ РАБОТАТЬ С pipeline_v2.py!

## Что Было Исправлено

### Проблема
После rebuild spatial-correlation-sampler Python все еще использовал старый `.so` файл из памяти, поэтому verification fails.

### Решение
Вместо `sys.exit(42)` внутри rebuild функции, теперь:
1. **Raise CUDAExtensionRebuiltError** после успешного rebuild
2. **cli.py ловит это исключение** и returns exit code 42
3. **pipeline_v2.py** передает этот exit code дальше
4. **Wrapper или ручной restart** видит код 42 и перезапускает

## Как Использовать

### Вариант 1: Auto-Restart Wrapper (Рекомендую!)

```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

**Что происходит:**
1. Первый запуск → rebuild → exit 42
2. Wrapper видит код 42 → автоматически restarts
3. Второй запуск → extension работает → processing completes ✅

### Вариант 2: Ручной Restart (Простой)

```bash
# Первый запуск
python pipeline_v2.py --input video.mp4
# Если вышел с кодом 42, просто запустите снова:
python pipeline_v2.py --input video.mp4
```

**Что происходит:**
1. Первый запуск → rebuild → exit 42 → видите сообщение
2. Вы руками запускаете команду снова
3. Второй запуск → extension работает → processing completes ✅

### Вариант 3: Shell Loop (В Скрипте)

```bash
#!/bin/bash
while true; do
    python pipeline_v2.py "$@"
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 42 ]; then
        echo "🔄 CUDA rebuild succeeded, restarting in 2 seconds..."
        sleep 2
        continue
    fi
    
    # Любой другой код - завершить
    exit $EXIT_CODE
done
```

## Что Увидите в Логах

### Первый Запуск (Rebuild)

```
[09:56:30] ❌ spatial-correlation-sampler: BROKEN
[09:56:30] Attempting auto-rebuild (default behavior on Vast.ai)...

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
   Raising exception to trigger restart...

================================================================================
CUDA EXTENSION REBUILT - RESTART REQUIRED
================================================================================

Exiting with code 42 to signal restart needed.
If using auto_restart_wrapper.py, restart will happen automatically.
Otherwise, please run the command again manually.
================================================================================
```

**Exit code: 42**

### Второй Запуск (После Restart)

```
[10:00:00] STARTUP: Validating CUDA dependencies...
[10:00:00] Checking spatial-correlation-sampler...
[10:00:00] ✅ spatial-correlation-sampler: OK
============================================================
✅ ALL STARTUP CHECKS PASSED
============================================================

[Processing continues normally...]
```

**Exit code: 0** ✅

## Почему Это Работает

### Архитектура

```
pipeline_v2.py
  ↓ sys.exit(main())
  ↓
cli.py → main()
  ↓
startup_checks()
  ↓
rebuild_spatial_correlation_sampler()
  ↓
✅ Compilation successful
  ↓
raise CUDAExtensionRebuiltError  # NEW!
  ↓
cli.py catches it → return 42
  ↓
pipeline_v2.py → sys.exit(42)
  ↓
Wrapper/Shell sees exit code 42 → RESTART
```

### Ключевые Изменения

1. **raft_wrapper.py**: `raise CUDAExtensionRebuiltError` вместо `sys.exit(42)`
2. **startup.py**: Re-raise исключение вверх
3. **cli.py**: Catch `CUDAExtensionRebuiltError` → return 42
4. **pipeline_v2.py**: Уже работает правильно (просто calls `sys.exit(main())`)

## Тестирование

### Локально (если есть CUDA mismatch)

```bash
# Тест 1: Manual restart
python pipeline_v2.py --input video.mp4
# Смотрите код выхода: echo $?
# Если 42 → запустите снова
python pipeline_v2.py --input video.mp4

# Тест 2: Auto-restart wrapper
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
# Должно работать с первого раза (wrapper сам restarts)
```

### На Vast.ai

```bash
# Deploy latest code
git pull origin main_rmsubs_roi_ar

# Run with auto-restart wrapper (recommended)
python auto_restart_wrapper.py python pipeline_v2.py \
    --input https://your-video-url.mp4 \
    --mode remove-subtitles \
    --roi 0.05,0.4,0.9,0.4

# First run: rebuild (~2-3 min) + restart + processing
# Subsequent runs: immediate processing (no rebuild needed)
```

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Success | Done! ✅ |
| 1 | Error | Check logs |
| 42 | Rebuild succeeded, restart needed | Run again or use wrapper |
| 130 | Interrupted (Ctrl+C) | User stopped |

## FAQ

### Q: Нужно ли перезапускать каждый раз?
**A:** Нет! Только первый раз на новом Vast.ai instance. После успешного rebuild extension сохраняется на диске, второй запуск работает сразу.

### Q: Что если забуду перезапустить?
**A:** Просто используйте wrapper (`auto_restart_wrapper.py`) - он сам перезапустит.

### Q: Можно ли обойтись без wrapper?
**A:** Да, просто запустите команду дважды вручную если видите exit code 42.

### Q: Сколько времени занимает rebuild?
**A:** 60-180 секунд в зависимости от GPU. Логи показывают прогресс с timestamps.

### Q: Что если rebuild fails?
**A:** Увидите ошибку с инструкциями. Обычно это означает:
- Нет build tools (gcc, nvcc) в Docker image
- Недостаточно RAM/disk space
- Network issues downloading dependencies

## Итого

✅ **pipeline_v2.py полностью поддерживается**
✅ **Exit code 42 работает правильно**
✅ **Auto-restart wrapper готов к использованию**
✅ **Timestamps показывают прогресс**
✅ **Manual restart тоже работает**

**Просто используйте wrapper и все будет работать автоматически!** 🎉

```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

