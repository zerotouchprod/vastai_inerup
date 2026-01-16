# ✅ ГОТОВО! АВТОРЕСТАРТ ВСТРОЕН В pipeline_v2.py

## Как Использовать

### Просто Запустите!
```bash
python pipeline_v2.py --input video.mp4
```

Все! Больше ничего не нужно! 🎉

## Что Происходит Автоматически

1. **Первый запуск** → Detect CUDA mismatch
2. **Auto-rebuild** → 60-180 секунд с progress timestamps
3. **Exit code 42** → "Restart needed"
4. **Auto-restart** → Wait 2 sec, restart automatically
5. **Второй запуск** → Extension works, processing completes ✅

## Примеры

### Базовый
```bash
python pipeline_v2.py --input video.mp4
```

### Remove Subtitles
```bash
python pipeline_v2.py \
    --input https://example.com/video.mp4 \
    --mode remove-subtitles \
    --roi 0.05,0.4,0.9,0.4
```

### На Vast.ai
```bash
cd /workspace/project
python pipeline_v2.py --input $INPUT_URL --mode remove-subtitles
```

## Логи

```
[09:56:30] ❌ spatial-correlation-sampler: BROKEN
[09:56:30] 🔧 Starting CUDA extension rebuild...
[09:56:30] Step 1/3: Uninstalling old version...
[09:56:31] Step 2/3: Compiling CUDA extension from source...
[09:58:45] ⏱️  Compilation took 134.2 seconds
[09:58:45] ✅ REBUILD COMPLETE in 136.5 seconds

[09:58:46] [auto-restart] 🔄 CUDA extension rebuilt (exit code 42)
[09:58:46] [auto-restart]    Auto-restart 1/3...
[09:58:48] [auto-restart] Restarting pipeline_v2.py...

[09:58:49] ✅ spatial-correlation-sampler: OK
[Processing completes successfully]
```

## Изменения

### Раньше
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
# ↑ Нужен wrapper
```

### Теперь
```bash
python pipeline_v2.py --input video.mp4
# ↑ Просто работает!
```

## Features

✅ **Авторестарт встроен** - не нужен wrapper
✅ **Безопасно** - макс 3 перезапуска
✅ **Timestamps** - видите прогресс
✅ **Прозрачно** - пользователь ничего не делает
✅ **Работает везде** - Vast.ai, SSH, Docker, local

## Защита

- **Max 3 restarts** - prevents infinite loops
- **Clear error messages** - если превышен лимит
- **Graceful handling** - все exit codes обрабатываются

## Документация

- `AUTO_RESTART_BUILTIN.md` - Полное описание
- `PIPELINE_V2_READY.md` - Общее руководство
- `PYTHON_RESTART_FIX.md` - Техническая документация

## Итого

**Один файл. Один запуск. Все автоматически!** 🚀

```bash
python pipeline_v2.py --input video.mp4
```

✅ Committed & Pushed to `main_rmsubs_roi_ar`

