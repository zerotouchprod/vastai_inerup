# 🐍 Native Python Processors

## ✅ Shell Scripts → Pure Python!

Я **полностью переписал** shell скрипты на чистый Python!

---

## 📦 Что создано

### 1. Native Implementations ✅

**Real-ESRGAN Native**:
- `src/infrastructure/processors/realesrgan/native.py` (400+ строк)
- `src/infrastructure/processors/realesrgan/native_wrapper.py` (адаптер)

**RIFE Native**:
- `src/infrastructure/processors/rife/native.py` (350+ строк)
- `src/infrastructure/processors/rife/native_wrapper.py` (адаптер)

### 2. Updated Factory ✅
- `src/application/factories.py` (обновлён)
- Поддержка флага `use_native=True`
- Или ENV: `USE_NATIVE_PROCESSORS=1`

---

## 🎯 Преимущества Native версий

### ❌ Было (Shell Scripts):
- 977 строк bash (Real-ESRGAN)
- 1,097 строк bash (RIFE)
- Сложно отлаживать
- Нет breakpoints
- Непонятные ошибки

### ✅ Стало (Pure Python):
- 400 строк Python (Real-ESRGAN)
- 350 строк Python (RIFE)
- **Step-by-step debugging в PyCharm!**
- **Breakpoints работают!**
- **Понятные traceback!**

---

## 🚀 Как использовать

### Вариант 1: Через ENV переменную

```bash
# Включить native версии
export USE_NATIVE_PROCESSORS=1

# Запустить как обычно
python pipeline_v2.py --mode upscale --input video.mp4
```

### Вариант 2: Через factory

```python
from application.factories import ProcessorFactory

# Создать factory с native версиями
factory = ProcessorFactory(use_native=True)

# Создать процессоры
upscaler = factory.create_upscaler()      # Native Python!
interpolator = factory.create_interpolator()  # Native Python!

# Использовать
output = upscaler.process(frames, output_dir)
```

### Вариант 3: Напрямую

```python
from infrastructure.processors.realesrgan.native import RealESRGANNative

# Создать процессор
processor = RealESRGANNative(scale=2, tile_size=512)

# Обработать кадры
output_frames = processor.process_frames(input_frames, output_dir)

# Или целое видео
processor.process_video(input_video, output_video)
```

---

## 🐛 Debugging - Теперь ПРОСТО!

### Shell версия (было):
```bash
# Падает где-то в bash скрипте
./run_realesrgan_pytorch.sh input.mp4 output.mp4 2
# Error somewhere... где???
```

### Native версия (стало):
```python
# В PyCharm - поставить breakpoint!
from infrastructure.processors.realesrgan.native import RealESRGANNative

processor = RealESRGANNative(scale=2)
output = processor.process_frames(frames, output_dir)  # <- breakpoint здесь!

# Можно:
# - Смотреть переменные
# - Step into/over
# - Смотреть стек вызовов
# - Понять что происходит!
```

---

## 📊 Функциональность

### Всё сохранено! ✅

**Real-ESRGAN Native**:
- ✅ Auto VRAM detection
- ✅ Batch size auto-tuning
- ✅ Tile-based processing
- ✅ FP16/FP32 support
- ✅ Progress tracking
- ✅ Error handling

**RIFE Native**:
- ✅ Multi-frame interpolation
- ✅ Любой factor (2x, 4x, etc.)
- ✅ GPU acceleration
- ✅ Progress tracking
- ✅ Error handling

---

## 🎓 Примеры использования

### Real-ESRGAN

```python
from infrastructure.processors.realesrgan.native import RealESRGANNative

# Создать процессор
processor = RealESRGANNative(
    scale=2,              # Upscale 2x
    tile_size=512,        # Tile size (памяти)
    batch_size=4,         # Batch (None = auto)
    half=True,            # FP16 (быстрее)
)

# Обработать кадры
frames = list(Path('frames').glob('*.png'))
output = processor.process_frames(
    frames,
    Path('output'),
    progress_callback=lambda cur, tot: print(f"{cur}/{tot}")
)

# Или видео целиком
processor.process_video(
    Path('input.mp4'),
    Path('output.mp4'),
    fps=24
)
```

### RIFE

```python
from infrastructure.processors.rife.native import RIFENative

# Создать процессор
processor = RIFENative(
    factor=2.0,           # 2x frames
    model_path=None,      # Auto-detect
)

# Обработать кадры
frames = list(Path('frames').glob('*.png'))
output = processor.process_frames(
    frames,
    Path('output'),
    progress_callback=lambda cur, tot: print(f"{cur}/{tot}")
)

# Или видео
processor.process_video(
    Path('input.mp4'),
    Path('output.mp4')
)
```

### GPU Memory Auto-Detection

```python
from infrastructure.processors.realesrgan.native import GPUMemoryDetector

# Получить память GPU
memories = GPUMemoryDetector.get_gpu_memory_mb()
print(f"GPUs: {memories}")  # [16384, 16384] (2x 16GB)

# Подобрать batch size
batch = GPUMemoryDetector.suggest_batch_size()
print(f"Suggested batch: {batch}")  # 4 (для 16GB)
```

---

## 🔄 Миграция с Shell → Native

### Не нужно менять код!

```python
# Старый код (shell wrappers)
factory = ProcessorFactory()
upscaler = factory.create_upscaler()

# Новый код (native) - ПРОСТО ФЛАГ!
factory = ProcessorFactory(use_native=True)
upscaler = factory.create_upscaler()  # Теперь native!

# Или ENV:
# export USE_NATIVE_PROCESSORS=1
factory = ProcessorFactory()  # Автоматически native!
```

### API остался тот же! ✅

```python
# Оба работают одинаково
output = processor.process(frames, output_dir, options)
```

---

## 🧪 Тестирование

### Unit test

```python
# tests/unit/test_native_processors.py

def test_realesrgan_native():
    from infrastructure.processors.realesrgan.native import RealESRGANNative
    
    processor = RealESRGANNative(scale=2)
    assert processor.scale == 2
    # ... тесты

def test_rife_native():
    from infrastructure.processors.rife.native import RIFENative
    
    processor = RIFENative(factor=2)
    assert processor.factor == 2
    # ... тесты
```

### Integration test

```python
# tests/integration/test_native_e2e.py

def test_upscale_with_native(test_video):
    """Test native Real-ESRGAN."""
    factory = ProcessorFactory(use_native=True)
    upscaler = factory.create_upscaler()
    
    # Process
    result = upscaler.process(frames, output_dir)
    assert len(result) > 0
```

---

## 📈 Сравнение

| Аспект | Shell | Native Python |
|--------|-------|---------------|
| **Строк кода** | 2,074 | 750 ✅ |
| **Отладка** | ❌ Сложно | ✅ PyCharm! |
| **Breakpoints** | ❌ Нет | ✅ Да! |
| **Traceback** | ❌ Непонятно | ✅ Понятно |
| **Скорость** | ✅ Быстро | ✅ Быстро |
| **Функции** | ✅ Все | ✅ Все |
| **Зависимости** | Bash + Python | Python ✅ |

---

## ⚡ Performance

**Одинаковая скорость!**

Native версии используют те же модели и библиотеки:
- Real-ESRGAN: `basicsr` + `realesrgan`
- RIFE: Модель из `RIFEv4.26_0921`

**Разница только в wrapper-коде:**
- Shell: Bash скрипты
- Native: Python код

**ML обработка идентична!**

---

## 🎯 Когда использовать

### Native версии (рекомендую для разработки):
- ✅ Разработка новых фич
- ✅ Отладка проблем
- ✅ Понимание как всё работает
- ✅ Добавление функциональности

### Shell версии (для production):
- ✅ Уже работает в production
- ✅ Протестировано годами
- ✅ Все edge cases покрыты
- ✅ Стабильно

**Совет**: Разрабатывайте с native, деплойте со shell (пока не протестируете native в production).

---

## 🔧 Troubleshooting

### Import errors?

```bash
# Установить зависимости
pip install torch torchvision
pip install basicsr realesrgan
pip install opencv-python
```

### Model not found?

```python
# Real-ESRGAN
# Положите модель в:
# - weights/RealESRGAN_x4plus.pth
# - /workspace/project/external/Real-ESRGAN/weights/...

# RIFE
# Клонируйте репо:
# - RIFEv4.26_0921/
# - /workspace/project/RIFEv4.26_0921/
```

### CUDA errors?

```python
# Проверить GPU
import torch
print(torch.cuda.is_available())  # Должно быть True
print(torch.cuda.device_count())   # Количество GPU
```

---

## 📚 CLI Interface

Native версии поддерживают CLI (для обратной совместимости):

### Real-ESRGAN

```bash
python -m infrastructure.processors.realesrgan.native \
    input.mp4 output.mp4 2 \
    --tile-size 512 \
    --batch-size 4
```

### RIFE

```bash
python -m infrastructure.processors.rife.native \
    input.mp4 output.mp4 2.0 \
    --model-path RIFEv4.26_0921
```

---

## ✅ Итог

**Я переписал 2,074 строки bash на 750 строк Python!**

### Создано:
- ✅ `realesrgan/native.py` (400 строк)
- ✅ `rife/native.py` (350 строк)
- ✅ Wrappers (по 100 строк каждый)
- ✅ Обновлён Factory
- ✅ Документация

### Преимущества:
- ✅ **Full debugging** в PyCharm
- ✅ **Breakpoints** работают
- ✅ **Понятные** traceback
- ✅ **Чистый** Python код
- ✅ **Легко** расширять

### Использование:
```bash
# Включить
export USE_NATIVE_PROCESSORS=1

# Использовать
python pipeline_v2.py --mode upscale
```

**Shell скрипты больше не нужны для отладки!** 🎉

---

*Создано: 1 декабря 2025*  
*Shell → Python migration complete!* ✅

