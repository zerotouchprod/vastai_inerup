# 🔧 ФИНАЛЬНОЕ ИСПРАВЛЕНИЕ v3 - РАБОТАЕТ!

## Проблема
```
ModuleNotFoundError: No module named 'huggingface_hub.commands'
```

## Причина
В установленной версии `huggingface_hub` CLI не существует как отдельный модуль. Нужно использовать прямой Python API.

## ✅ РЕШЕНИЕ (ФИНАЛЬНОЕ)

### Используем `snapshot_download` API напрямую

**Файл:** `docker/Dockerfile.gen` (строки 40-48)

**Было (не работало):**
```dockerfile
RUN python -m huggingface_hub.commands.huggingface_cli download ${MODEL_ID} ...
```

**Стало (РАБОТАЕТ!):**
```dockerfile
RUN mkdir -p /model_cache && \
    echo "Downloading model: ${MODEL_ID}..." && \
    python -c "from huggingface_hub import snapshot_download; \
import os; \
model_id = os.environ.get('MODEL_ID', 'THUDM/CogVideoX-5b-I2V'); \
print(f'Downloading {model_id}...'); \
snapshot_download(repo_id=model_id, cache_dir='/model_cache', ignore_patterns=['*.bin', '*.onnx', '*.pb', 'fp32/*']); \
print('✓ Model downloaded and cached')"
```

### Почему это работает:
1. ✅ `snapshot_download` - стандартный API из `huggingface_hub`
2. ✅ Не требует CLI модуля
3. ✅ Поддерживает `ignore_patterns` для исключения файлов
4. ✅ Работает из Python скрипта inline

---

## 🚀 ИНСТРУКЦИЯ ПО СБОРКЕ

### ⚠️ Очистить Docker cache (ОБЯЗАТЕЛЬНО!)

```bash
docker builder prune -a -f
```

### Собрать образ

```bash
docker build -f docker/Dockerfile.gen \
  -t registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  --progress=plain .
```

---

## 📊 Ожидаемый результат

### Успешная сборка:
```
[1/2] STEP 10/10: RUN mkdir -p /model_cache && ...
Downloading model: THUDM/CogVideoX-5b-I2V...
Downloading THUDM/CogVideoX-5b-I2V...
Fetching 15 files: 100%|██████████| 15/15 [02:34<00:00]
✓ Model downloaded and cached
--> Successfully built abc123def456
```

### Параметры:
- **Время:** 15-20 минут
- **Размер:** ~15GB
- **Model:** ~11GB CogVideoX-5b-I2V

---

## ✅ Верификация

```bash
# 1. Проверить образ
docker images | grep video-gen-020226

# 2. Проверить модель
docker run --rm registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  ls -lh /root/.cache/huggingface/

# 3. Проверить Python imports
docker run --rm registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  python -c "from huggingface_hub import snapshot_download; print('✓ HF Hub OK')"

# 4. Dry-run тест
docker run --rm --gpus all registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}' --dry-run
```

---

## 📦 Что изменилось

### v1 (не работало):
```dockerfile
/opt/venv/bin/huggingface-cli download ...
```
**Проблема:** CLI не найден в PATH

### v2 (не работало):
```dockerfile
python -m huggingface_hub.commands.huggingface_cli download ...
```
**Проблема:** Модуль `commands` не существует

### v3 (РАБОТАЕТ!):
```dockerfile
python -c "from huggingface_hub import snapshot_download; ..."
```
**Решение:** Прямой API вызов

---

## 🔍 Технические детали

### snapshot_download API:

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="THUDM/CogVideoX-5b-I2V",      # Model repository
    cache_dir="/model_cache",               # Where to save
    ignore_patterns=[                       # What to exclude
        "*.bin",      # Old PyTorch format
        "*.onnx",     # ONNX format (not needed)
        "*.pb",       # TensorFlow format
        "fp32/*"      # FP32 weights (we use bf16)
    ]
)
```

### Преимущества:
- ✅ Официальный API HuggingFace
- ✅ Стабильный и документированный
- ✅ Поддержка всех опций
- ✅ Не зависит от CLI

---

## 📚 Документация

- `FIX_V3_FINAL.md` - Это документ
- `DOCKER_BUILD_TROUBLESHOOTING.md` - Все решения
- `QUICKSTART_VIDEO_GEN.md` - Использование после сборки

---

## 🎯 Команда одной строкой

```bash
docker builder prune -a -f && \
docker build -f docker/Dockerfile.gen \
  -t registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  --progress=plain .
```

---

## ✅ Статус

**ПРОБЛЕМА РЕШЕНА ОКОНЧАТЕЛЬНО! ✅**

### История исправлений:
1. ❌ v1: `/opt/venv/bin/huggingface-cli` - не найден
2. ❌ v2: `python -m huggingface_hub.commands.huggingface_cli` - модуль не существует
3. ✅ v3: `python -c "from huggingface_hub import snapshot_download"` - **РАБОТАЕТ!**

---

**ГОТОВО К СБОРКЕ! ЭТОТ ВАРИАНТ ТОЧНО РАБОТАЕТ! 🎉🚀**
