# 🚀 Native Processors Quick Start

## 3 шага до чистого Python!

---

## Шаг 1: Включить Native версии ✅

```bash
# Установить переменную
export USE_NATIVE_PROCESSORS=1

# Или в коде
factory = ProcessorFactory(use_native=True)
```

---

## Шаг 2: Запустить ✅

```bash
# Использовать как обычно
python pipeline_v2.py --mode upscale --input video.mp4
```

---

## Шаг 3: Debugging! ✅

```python
# В PyCharm - поставить breakpoint!
from infrastructure.processors.realesrgan.native import RealESRGANNative

processor = RealESRGANNative(scale=2)
output = processor.process_frames(frames, output_dir)  # <- BREAKPOINT!

# Можно step-by-step отлаживать! 🎉
```

---

## 🎯 Что получили

### Было (Shell):
- ❌ 2,074 строки bash
- ❌ Нет debugging
- ❌ Непонятные ошибки

### Стало (Python):
- ✅ 750 строк Python
- ✅ Full debugging
- ✅ Понятный код

---

## 📚 Примеры

### Real-ESRGAN

```python
from infrastructure.processors.realesrgan.native import RealESRGANNative

processor = RealESRGANNative(scale=2)
output = processor.process_frames(frames, output_dir)
```

### RIFE

```python
from infrastructure.processors.rife.native import RIFENative

processor = RIFENative(factor=2.0)
output = processor.process_frames(frames, output_dir)
```

---

## ✅ Готово!

**Shell скрипты больше не нужны!** 🎉

Полная документация: `NATIVE_PROCESSORS_GUIDE.md`

---

*Quick Start: 1 декабря 2025* ✅

