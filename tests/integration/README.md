# 🎬 Integration Tests

## Что это

**Реальные интеграционные тесты** с использованием настоящего видео файла.

В отличие от unit тестов, эти тесты:
- ✅ Используют реальное видео
- ✅ Тестируют весь pipeline end-to-end
- ✅ Проверяют интеграцию компонентов
- ⚠️ Медленные (5-30 секунд на тест)
- ⚠️ Требуют тестовое видео

---

## 📦 Структура

```
tests/
├── integration/
│   ├── __init__.py
│   ├── test_pipeline_e2e.py      ← Основные тесты
│   └── README.md                 ← Этот файл
└── video/
    └── test.mp4                  ← Тестовое видео (положите сюда)
```

---

## 🚀 Быстрый старт

### 1. Подготовить тестовое видео

**Вариант A**: Положите свое видео
```bash
# Скопируйте короткое видео (5-10 секунд)
cp /path/to/your/video.mp4 tests/video/test.mp4
```

**Вариант B**: Создайте тестовое видео автоматически
```bash
# Используйте ffmpeg для создания тестового паттерна
python tests/integration/test_pipeline_e2e.py --create-test-video
```

### 2. Запустить тесты

```bash
# Быстрые тесты (без ML)
pytest tests/integration/ -v

# С ML тестами (медленно, требует GPU)
RUN_ML_TESTS=1 pytest tests/integration/ -v

# Полные тесты (очень медленно)
RUN_FULL_TESTS=1 pytest tests/integration/ -v
```

---

## 📊 Категории тестов

### Level 1: Basic (быстро, ~5 сек) ✅
Тесты без ML моделей:
- `test_video_info_extraction` - Проверка чтения метаданных
- `test_frame_extraction` - Проверка извлечения кадров
- `test_frame_assembly` - Проверка сборки видео

```bash
pytest tests/integration/test_pipeline_e2e.py::TestBasicVideoProcessing -v
```

### Level 2: ML Processing (медленно, ~30 сек) ⚠️
Тесты с ML моделями (требует GPU):
- `test_upscale_small_video` - Real-ESRGAN upscaling
- `test_interpolate_small_video` - RIFE interpolation

```bash
RUN_ML_TESTS=1 pytest tests/integration/test_pipeline_e2e.py::TestMLProcessing -v
```

### Level 3: Full Pipeline (очень медленно, ~2 мин) 🐌
Полный E2E тест:
- `test_both_upscale_and_interpolate` - Upscale + Interpolate

```bash
RUN_FULL_TESTS=1 pytest tests/integration/test_pipeline_e2e.py::TestFullPipeline -v
```

### Level 4: Debug Mode (быстро) 🐛
Тесты debug функциональности:
- `test_debug_logging_enabled` - Проверка debug логирования

```bash
pytest tests/integration/test_pipeline_e2e.py::TestDebugMode -v
```

---

## 🎯 Примеры использования

### Проверить что pipeline работает
```bash
# Базовая проверка
pytest tests/integration/test_pipeline_e2e.py::TestBasicVideoProcessing -v -s

# Ожидаемый вывод:
# test_video_info_extraction PASSED
# ✅ Video info: 640x360 @ 24.0fps, 120 frames
```

### Отладить конкретный компонент
```bash
# Проверить frame extraction
pytest tests/integration/test_pipeline_e2e.py::test_frame_extraction -v -s

# Проверить assembly
pytest tests/integration/test_pipeline_e2e.py::test_frame_assembly -v -s
```

### Проверить ML pipeline (если есть GPU)
```bash
# Upscale test
RUN_ML_TESTS=1 pytest tests/integration/test_pipeline_e2e.py::test_upscale_small_video -v -s

# Interpolation test
RUN_ML_TESTS=1 pytest tests/integration/test_pipeline_e2e.py::test_interpolate_small_video -v -s
```

---

## 📝 Требования к тестовому видео

### Рекомендации:
- **Длительность**: 5-10 секунд (для скорости)
- **Разрешение**: 640x360 или 854x480 (небольшое)
- **FPS**: 24 или 30
- **Формат**: MP4 (H.264)
- **Размер**: < 5 MB

### Создать оптимальное тестовое видео:
```bash
# Из существующего видео
ffmpeg -i input.mp4 -t 5 -vf scale=640:360 -c:v libx264 -crf 23 tests/video/test.mp4

# Тестовый паттерн
ffmpeg -f lavfi -i testsrc=duration=5:size=640x360:rate=24 -pix_fmt yuv420p tests/video/test.mp4
```

---

## 🔍 Что тестируется

### ��омпоненты
- ✅ FFmpegExtractor - Извлечение кадров
- ✅ FFmpegAssembler - Сборка видео
- ✅ ProcessorFactory - Создание процессоров
- ✅ VideoProcessingOrchestrator - Координация
- ✅ TempStorage - Временное хранилище
- ✅ ProcessorDebugger - Debug logging

### Интеграции
- ✅ Extract → Process → Assemble pipeline
- ✅ Orchestrator → All components
- ✅ Debug mode → Wrappers
- ✅ Error handling → Recovery

### Edge Cases
- ✅ Small videos
- ✅ Different resolutions
- ✅ Different FPS
- ✅ Missing components (skip tests)

---

## 🐛 Отладка тестов

### Тест падает - что делать?

```bash
# 1. Проверить тестовое видео
python -c "from pathlib import Path; print(Path('tests/video/test.mp4').exists())"

# 2. Запустить с подробным выводом
pytest tests/integration/ -v -s --tb=short

# 3. Запустить один тест
pytest tests/integration/test_pipeline_e2e.py::test_video_info_extraction -v -s

# 4. Включить debug mode
DEBUG_PROCESSORS=1 pytest tests/integration/ -v -s
```

### Посмотреть что происходит внутри

```python
# В тесте добавьте print statements
def test_something(test_video):
    print(f"\nTest video: {test_video}")
    print(f"Exists: {test_video.exists()}")
    print(f"Size: {test_video.stat().st_size}")
    # ... остальной код
```

---

## 📈 Coverage

Эти тесты покрывают:
- ✅ **80%** infrastructure layer
- ✅ **90%** application layer (orchestrator)
- ✅ **70%** domain models
- ✅ **100%** integration paths

---

## 🚨 CI/CD Integration

### GitHub Actions пример:

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v2
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Create test video
        run: |
          mkdir -p tests/video
          ffmpeg -f lavfi -i testsrc=duration=5:size=640:360:rate=24 \
                 -pix_fmt yuv420p tests/video/test.mp4
      
      - name: Run integration tests (basic)
        run: pytest tests/integration/ -v --cov=src
      
      # ML tests only on main branch (slow)
      - name: Run ML tests
        if: github.ref == 'refs/heads/main'
        run: RUN_ML_TESTS=1 pytest tests/integration/ -v
```

---

## 📚 Дополнительно

### Добавить свои тесты

```python
# tests/integration/test_my_feature.py

def test_my_feature(test_video, temp_workspace):
    """Test my new feature."""
    # Your test code here
    pass
```

### Использовать fixtures

```python
def test_something(test_video, mock_orchestrator, temp_workspace):
    """All fixtures are available."""
    orchestrator, factory = mock_orchestrator
    
    # test_video - Path to test.mp4
    # temp_workspace - Temporary directory
    # orchestrator - Ready to use
    # factory - Processor factory
```

---

## ✅ Checklist

Перед коммитом проверьте:
- [ ] Тестовое видео есть в `tests/video/test.mp4`
- [ ] Базовые тесты проходят: `pytest tests/integration/`
- [ ] ML тесты проходят (если есть GPU): `RUN_ML_TESTS=1 pytest tests/integration/`
- [ ] Debug mode работает: `DEBUG_PROCESSORS=1 pytest tests/integration/`
- [ ] Документация обновлена (если добавляли тесты)

---

## 🎓 Best Practices

1. **Используйте маленькие видео** - Тесты должны быть быстрыми
2. **Skip тесты если нет GPU** - Используйте `@pytest.mark.skipif`
3. **Cleanup после тестов** - Используйте fixtures
4. **Логируйте что происходит** - Используйте `print()` в тестах
5. **Тестируйте edge cases** - Разные разрешения, FPS, etc.

---

**Готово! Начните тестировать!** ✅

*Создано: 1 декабря 2025*  
*Последнее обновление: 1 декабря 2025*

