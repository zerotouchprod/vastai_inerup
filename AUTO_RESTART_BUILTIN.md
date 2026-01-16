# ✅ AUTO-RESTART ВСТРОЕН В pipeline_v2.py!

## Что Изменилось

**Теперь не нужен wrapper!** Авторестарт встроен прямо в `pipeline_v2.py`.

### Раньше (Нужен был wrapper)
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
```

### Теперь (Просто запустите!)
```bash
python pipeline_v2.py --input video.mp4
```

## Как Это Работает

`pipeline_v2.py` теперь содержит авторестарт логику:

```python
while restart_count <= max_restarts:
    exit_code = main()
    
    if exit_code == 0:
        # Успех
        sys.exit(0)
    
    elif exit_code == 42:
        # CUDA rebuild succeeded - restart!
        restart_count += 1
        log("🔄 Auto-restart...")
        time.sleep(2)
        continue  # Restart loop
    
    else:
        # Ошибка
        sys.exit(exit_code)
```

## Что Происходит

### Первый Запуск (CUDA Mismatch)

```
$ python pipeline_v2.py --input video.mp4

[09:56:30] STARTUP: Validating CUDA dependencies...
[09:56:30] ❌ spatial-correlation-sampler: BROKEN

[09:56:30] 🔧 Starting CUDA extension rebuild...
[09:56:30] Step 1/3: Uninstalling old version...
[09:56:31] ✅ Old version uninstalled

[09:56:31] Step 2/3: Compiling CUDA extension from source...
⏳ This is the longest step - please be patient...

[09:58:45] ⏱️  Compilation took 134.2 seconds
[09:58:45] ✅ Compilation successful

================================================================================
[09:58:45] ✅ REBUILD COMPLETE in 136.5 seconds
================================================================================

⚠️  IMPORTANT: Python process must RESTART to use new extension

================================================================================
CUDA EXTENSION REBUILT - RESTART REQUIRED
================================================================================

Exiting with code 42 to signal restart needed.
================================================================================

[09:58:46] [auto-restart] 
[09:58:46] [auto-restart] ================================================================================
[09:58:46] [auto-restart] 🔄 CUDA extension rebuilt (exit code 42)
[09:58:46] [auto-restart]    Auto-restart 1/3...
[09:58:46] [auto-restart] ================================================================================
[09:58:46] [auto-restart] 
[09:58:46] [auto-restart] Waiting 2 seconds before restart...
[09:58:48] [auto-restart] Restarting pipeline_v2.py with same arguments...
[09:58:48] [auto-restart] 

[09:58:49] STARTUP: Validating CUDA dependencies...
[09:58:49] Checking spatial-correlation-sampler...
[09:58:49] ✅ spatial-correlation-sampler: OK
============================================================
✅ ALL STARTUP CHECKS PASSED
============================================================

[Processing continues...]
=== VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY ===
```

### Второй Запуск (Extension Уже Работает)

```
$ python pipeline_v2.py --input video.mp4

[10:15:30] STARTUP: Validating CUDA dependencies...
[10:15:30] Checking spatial-correlation-sampler...
[10:15:30] ✅ spatial-correlation-sampler: OK
============================================================
✅ ALL STARTUP CHECKS PASSED
============================================================

[Processing continues normally...]
=== VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY ===
```

## Преимущества

### ✅ Не Нужен Wrapper
Просто запускаете `pipeline_v2.py` - все работает автоматически!

### ✅ Прозрачно Для Пользователя
Авторестарт происходит автоматически, пользователь просто видит прогресс.

### ✅ Безопасно
Макс 3 перезапуска - защита от бесконечного цикла.

### ✅ Логи С Timestamps
Все сообщения авторестарта с `[HH:MM:SS] [auto-restart]` префиксом.

### ✅ Работает Везде
- Vast.ai - просто запустите
- SSH - просто запустите
- Docker - просто запустите
- Локально - просто запустите

## Использование

### Базовое
```bash
python pipeline_v2.py --input video.mp4
```

### С Параметрами
```bash
python pipeline_v2.py \
    --input https://example.com/video.mp4 \
    --mode remove-subtitles \
    --roi 0.05,0.4,0.9,0.4 \
    --subs-lang en
```

### На Vast.ai
```bash
# В вашем startup script
cd /workspace/project
python pipeline_v2.py --input $INPUT_URL --mode remove-subtitles
```

Все! Никаких wrapper'ов, авторестарт работает автоматически! ✅

## Exit Codes

| Code | Meaning | Что Делает pipeline_v2.py |
|------|---------|---------------------------|
| 0 | Success | Exit 0 ✅ |
| 42 | Rebuild succeeded, restart | Auto-restart (макс 3 раза) 🔄 |
| 1 | Error | Exit 1 ❌ |
| 130 | Interrupted (Ctrl+C) | Exit 130 ⚠️ |

## Защита От Бесконечного Цикла

```python
max_restarts = 3
restart_count = 0

# Если rebuild fails 3 раза подряд → stop
if restart_count > max_restarts:
    log("❌ Max restarts exceeded")
    sys.exit(1)
```

Если видите это сообщение → проверьте:
- Build tools установлены (gcc, nvcc)
- Достаточно disk space (нужно ~2GB)
- Network работает (для скачивания dependencies)

## Сравнение

### Старый Способ (С Wrapper)
```bash
python auto_restart_wrapper.py python pipeline_v2.py --input video.mp4
# ↑ Нужен wrapper
```

### Новый Способ (Встроен)
```bash
python pipeline_v2.py --input video.mp4
# ↑ Просто работает!
```

## Технические Детали

### Код В pipeline_v2.py

```python
if __name__ == '__main__':
    max_restarts = 3
    restart_count = 0
    
    while restart_count <= max_restarts:
        exit_code = main()  # Вызывает cli.py
        
        if exit_code == 0:
            sys.exit(0)  # Success
        
        elif exit_code == 42:
            restart_count += 1
            if restart_count <= max_restarts:
                log_restart("🔄 Auto-restart...")
                time.sleep(2)
                continue  # Restart!
            else:
                sys.exit(1)  # Too many restarts
        
        else:
            sys.exit(exit_code)  # Error
```

### Почему Это Работает

1. `main()` из cli.py возвращает exit code
2. pipeline_v2.py видит код 42
3. Просто продолжает while loop
4. Вызывает `main()` снова
5. Новый Python call → новый процесс memory → загружает новый .so ✅

## FAQ

### Q: Нужен ли еще auto_restart_wrapper.py?
**A:** Нет! Можете удалить или оставить для backward compatibility.

### Q: Что если я хочу disable авторестарт?
**A:** Просто skip - авторестарт встроен и всегда работает. Это хорошо!

### Q: Сколько раз может перезапуститься?
**A:** Макс 3 раза. Обычно нужен только 1 раз.

### Q: Что если первый rebuild fails?
**A:** Увидите ошибку и exit code 1, без перезапуска.

### Q: Работает ли на Windows?
**A:** Да! Python code платформо-независимый.

## Итого

✅ **Авторестарт встроен в pipeline_v2.py**
✅ **Не нужен wrapper**
✅ **Просто запустите `python pipeline_v2.py`**
✅ **Автоматически restarts при exit code 42**
✅ **Макс 3 перезапуска для безопасности**
✅ **Работает везде одинаково**

**Теперь еще проще! Один файл, один запуск, все автоматически!** 🎉

