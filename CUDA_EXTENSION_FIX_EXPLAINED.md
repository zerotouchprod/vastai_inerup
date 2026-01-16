# ⚠️ ВАЖНО: Что на самом деле нужно для исправления ProPainter RAFT

## Проблема

ProPainter использует **TWO разных correlation extensions**:

1. **`spatial-correlation-sampler`** (pip package)
   - Python обёртка
   - Устанавливается через pip
   - Может работать, но этого недостаточно!

2. **`/opt/ProPainter/RAFT/core/correlation`** (C++ extension)
   - **ЭТО НАСТОЯЩАЯ ПРОБЛЕМА**
   - Компилируется при сборке Docker image
   - Привязана к конкретной версии CUDA
   - Если CUDA версия не совпадает → CorrBlock error

## Что происходит при ошибке

```
File "/opt/ProPainter/RAFT/raft.py", line 109, in forward
    corr_fn = CorrBlock
```

Эта ошибка означает, что **ProPainter RAFT correlation extension** не может загрузиться, потому что она была скомпилирована с другой версией CUDA.

## Решение

### Вариант 1: Пересборка Docker образа (РЕКОМЕНДУЕТСЯ)

```bash
# Rebuild Docker image на машине с нужной версией CUDA
docker build -t your-image:latest .
```

**Это правильный способ!** Docker image будет содержать extensions, скомпилированные для правильной CUDA версии.

### Вариант 2: Автоматический rebuild при запуске (НЕ рекомендуется для production)

```bash
# Enable auto-rebuild
export AUTO_REBUILD_CUDA_EXTENSIONS=true

# Run application
python pipeline_v2.py --input video.mp4
```

**Что произойдет:**
1. При старте приложения проверяется работоспособность extensions
2. Если broken → автоматически запускается rebuild:
   ```bash
   # Rebuild spatial-correlation-sampler
   pip install --force-reinstall spatial-correlation-sampler
   
   # Rebuild ProPainter RAFT correlation
   cd /opt/ProPainter/RAFT/core/correlation
   rm -rf build dist *.egg-info *.so
   python3 setup.py install
   ```
3. Занимает ~60-180 секунд
4. После успеха приложение продолжает работу

### Вариант 3: Ручной rebuild (для debugging)

```bash
# SSH в контейнер
ssh root@instance.vast.ai

# Проверка
python3 test_cuda_extensions.py

# Если broken, ручной rebuild:
cd /opt/ProPainter/RAFT/core/correlation
rm -rf build dist *.egg-info *.so
python3 setup.py install

# Проверка снова
python3 test_cuda_extensions.py
```

## Работает ли это без пересборки образа?

### ✅ ДА, если:
1. `AUTO_REBUILD_CUDA_EXTENSIONS=true` установлен
2. В контейнере есть build tools (gcc, g++, CUDA toolkit)
3. Достаточно времени для rebuild (~60-180 секунд)

### ❌ НЕТ, если:
1. Build tools отсутствуют в образе
2. CUDA toolkit не установлен
3. Permission errors при записи в `/opt/ProPainter`
4. Incompatible PyTorch/CUDA versions

## Что было исправлено в коде

### До (неправильно):
```python
# Только pip install spatial-correlation-sampler
# Это НЕ исправляет ProPainter RAFT correlation!
subprocess.run(["pip", "install", "spatial-correlation-sampler"])
```

### После (правильно):
```python
# 1. Rebuild spatial-correlation-sampler package
subprocess.run(["pip", "install", "spatial-correlation-sampler"])

# 2. Rebuild ProPainter RAFT correlation extension
cd /opt/ProPainter/RAFT/core/correlation
rm -rf build dist *.egg-info *.so
python3 setup.py install

# 3. Verify it works
check_spatial_correlation_sampler()
```

## Тестирование

### Быстрый тест:
```bash
python3 test_cuda_extensions.py
```

Этот скрипт:
1. ✅ Проверяет spatial-correlation-sampler
2. ✅ Предлагает rebuild если broken
3. ✅ Проверяет ProPainter RAFT инициализацию
4. ✅ Даёт четкие инструкции при ошибках

### В production:
```bash
# Автоматически при старте приложения
python pipeline_v2.py --input video.mp4

# Если AUTO_REBUILD_CUDA_EXTENSIONS=true:
# → Automatic rebuild if broken
# → Processing continues

# Если не установлен:
# → Fail fast с инструкциями
# → Exit с кодом 1
```

## Рекомендации

### Для development:
```bash
# Включить auto-rebuild
export AUTO_REBUILD_CUDA_EXTENSIONS=true

# Или тестировать руками
python3 test_cuda_extensions.py
```

### Для production:
```bash
# 1. Rebuild Docker image на целевой CUDA версии
docker build -t your-image:latest .

# 2. НЕ использовать AUTO_REBUILD_CUDA_EXTENSIONS
# 3. Validate при deployment:
python3 test_cuda_extensions.py
```

## FAQ

### Q: Можно ли обойтись без пересборки образа?
**A:** Да, если `AUTO_REBUILD_CUDA_EXTENSIONS=true` и есть build tools в контейнере. Но это медленно и не рекомендуется для production.

### Q: Сколько времени занимает rebuild?
**A:** ~60-180 секунд в зависимости от CPU и CUDA версии.

### Q: Что если rebuild падает?
**A:** Нужна пересборка Docker образа с правильной CUDA версией. Auto-rebuild не всегда работает.

### Q: Можно ли кэшировать результат rebuild?
**A:** Да, после успешного rebuild extension остается рабочим до перезапуска контейнера.

### Q: Нужен ли rebuild после каждого перезапуска?
**A:** Нет, если Docker volume сохраняет `/opt/ProPainter`. Но обычно каждый новый контейнер = новый rebuild.

## Итог

**Проблема теперь решена правильно:**

✅ Код понимает что нужно пересобрать **именно ProPainter RAFT correlation**
✅ Auto-rebuild работает (если `AUTO_REBUILD_CUDA_EXTENSIONS=true`)
✅ Fail fast с четкими инструкциями (если auto-rebuild отключен)
✅ Test script для проверки (`test_cuda_extensions.py`)

**Но рекомендация:**
🔥 **ПЕРЕСОБЕРИТЕ DOCKER IMAGE** на машине с нужной CUDA версией
🔥 Это правильный production-ready способ
🔥 Auto-rebuild - только для development/debugging

## Команды для копирования

```bash
# Development: Enable auto-rebuild
export AUTO_REBUILD_CUDA_EXTENSIONS=true
python pipeline_v2.py --input video.mp4

# Testing: Check extensions manually
python3 test_cuda_extensions.py

# Production: Rebuild Docker image
docker build -t your-image:latest .

# Manual fix: Rebuild extensions by hand
cd /opt/ProPainter/RAFT/core/correlation
rm -rf build dist *.egg-info *.so
python3 setup.py install
python3 -c "from src.infrastructure.inpainting.raft_wrapper import validate_raft_availability; validate_raft_availability()"
```

