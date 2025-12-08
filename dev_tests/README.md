# Development Test Scripts

Эта папка содержит ad-hoc тестовые скрипты, которые использовались во время разработки и отладки.

## ⚠️ Важно

Эти скрипты **НЕ являются частью официального test suite**. Официальные тесты находятся в `tests/`.

## 📝 Назначение

Эти скрипты использовались для:
- Быстрой проверки функциональности во время разработки
- Debugging конкретных проблем
- Проверки availability ML библиотек
- Тестирования refactoring шагов

## 🧪 Официальные Тесты

Для запуска официальных тестов используйте:

```bash
# Unit тесты
pytest tests/unit/ -v

# Integration тесты
pytest tests/integration/ -v

# Все тесты
pytest tests/ -v
```

## 📋 Список Скриптов

- `test_native_availability.py` - проверка доступности native processors
- `test_both_mode.py` - тест режима "both" с native processors
- `test_cuda_fallback.py` - проверка fallback на CPU
- `test_rife_model_path.py` - проверка путей к RIFE моделям
- `test_rife_import_fix.py` - отладка импортов RIFE
- `test_batch_rife_import.py` - проверка импортов batch_rife
- `test_fps_calculation.py` - проверка вычисления FPS
- `test_logs_debug.py` - отладка логирования
- `test_monitor_fix.py` - fixes для monitor
- `test_monitor_timestamp.py` - проверка timestamps
- `test_realesrgan_logging.py` - логирование Real-ESRGAN
- `test_realesrgan_performance.py` - тесты производительности
- `test_upscale_fps.py` - проверка FPS после upscale
- `test_upscale_fps_real.py` - реальные тесты upscale FPS

## 🔧 Использование

Эти скрипты можно запускать напрямую:

```bash
python dev_tests/test_native_availability.py
```

**Примечание**: Некоторые скрипты требуют PyTorch+CUDA и будут падать на локальной машине (это нормально).

## 📚 Refer to Official Tests

Если вам нужны примеры тестирования, смотрите:
- `tests/unit/` - unit тесты с моками
- `tests/integration/` - integration тесты с реальным видео

---

*Скрипты перемещены в dev_tests/ 8 декабря 2025 для организации кода.*
