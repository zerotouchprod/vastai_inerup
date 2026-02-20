# 🔧 ВТОРОЕ ИСПРАВЛЕНИЕ - ФИНАЛЬНОЕ

## Проблема (повторная)
```
/bin/sh: 1: /opt/venv/bin/huggingface-cli: not found
Error: exit status 127
```

## Причина
После установки `huggingface_hub[cli]`, CLI команда устанавливается как Python модуль, а не как standalone executable в `/opt/venv/bin/`.

## Решение ✅ (ФИНАЛЬНОЕ)

### Исправление в `docker/Dockerfile.gen` (строка 42)

**Было (первое исправление):**
```dockerfile
RUN /opt/venv/bin/huggingface-cli download ${MODEL_ID} ...
```

**Стало (второе исправление):**
```dockerfile
RUN python -m huggingface_hub.commands.huggingface_cli download ${MODEL_ID} \
    --exclude "*.bin" "*.onnx" "*.pb" "fp32/*" \
    --cache-dir /model_cache
```

**Объяснение:**
- `huggingface_hub[cli]` устанавливает CLI как Python модуль
- Правильный способ вызова: `python -m huggingface_hub.commands.huggingface_cli`
- Это работает в любом окружении (venv, system python, etc.)

---

## Проверка исправления

### 1. Проверить что изменение применено:
```bash
grep "python -m huggingface_hub" docker/Dockerfile.gen
```

**Должно быть:**
```
    python -m huggingface_hub.commands.huggingface_cli download ${MODEL_ID} \
```

### 2. Очистить Docker cache (важно!):
```bash
# Удалить старые слои с ошибкой
docker builder prune -a -f

# Или полная очистка
docker system prune -a -f
```

### 3. Пересобрать образ:
```bash
docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

---

## Альтернативные решения (если основное не работает)

### Вариант A: Установить huggingface-cli отдельно
```dockerfile
# В Dockerfile после установки requirements
RUN pip install --no-cache-dir huggingface-cli
```

### Вариант B: Использовать snapshot_download из Python
```dockerfile
RUN python -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='${MODEL_ID}',
    cache_dir='/model_cache',
    ignore_patterns=['*.bin', '*.onnx', '*.pb', 'fp32/*']
)
"
```

### Вариант C: Использовать wget/curl (не рекомендуется)
```dockerfile
# Скачать модель через wget
RUN wget -P /model_cache https://huggingface.co/...
```

---

## Обновленные файлы

1. ✅ `docker/Dockerfile.gen` - исправлена команда загрузки модели
2. ✅ `DOCKER_BUILD_TROUBLESHOOTING.md` - обновлены решения
3. ✅ `scripts/build_video_gen.sh` - обновлена верификация

---

## Команды для сборки

### Рекомендуемый способ (с очисткой cache):
```bash
# 1. Очистить Docker cache
docker builder prune -a -f

# 2. Собрать образ
docker build -f docker/Dockerfile.gen \
  -t registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  --progress=plain \
  --no-cache \
  .
```

### Быстрый способ (если уверены что cache чист):
```bash
docker build -f docker/Dockerfile.gen \
  -t registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  --progress=plain \
  .
```

---

## Ожидаемый результат

### Успешная сборка:
```
[1/2] STEP 10/10: RUN mkdir -p /model_cache && ...
Downloading model: THUDM/CogVideoX-5b-I2V...
Fetching 15 files: 100%|██████████| 15/15 [02:34<00:00, 10.32s/file]
✓ Model downloaded and cached
--> abc123def456

[2/2] STEP 1/20: FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime
...
Successfully tagged registry.gitlab.com/gfever/vastai_interup:video-gen-020226
```

### Время сборки:
- **Stage 1:** ~10-15 минут (model download)
- **Stage 2:** ~2-3 минуты
- **Итого:** ~15-20 минут

---

## Верификация после сборки

```bash
# 1. Проверить что образ создан
docker images | grep video-gen

# 2. Проверить что модель в образе
docker run --rm registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  ls -lh /root/.cache/huggingface/

# 3. Проверить HuggingFace CLI
docker run --rm registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  python -m huggingface_hub.commands.huggingface_cli --version

# 4. Проверить PyTorch
docker run --rm registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  python -c "import torch; print(torch.__version__); print(torch.cuda.is_available())"

# 5. Dry-run тест
docker run --rm --gpus all registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}' --dry-run
```

---

## Если проблема сохраняется

### Debug: Проверить что установлено в venv
```bash
# Собрать только Stage 1
docker build -f docker/Dockerfile.gen --target builder -t debug-builder .

# Войти в контейнер
docker run -it --rm debug-builder /bin/bash

# Внутри контейнера:
source /opt/venv/bin/activate
pip list | grep huggingface
which huggingface-cli
python -m huggingface_hub.commands.huggingface_cli --version
ls -la /opt/venv/bin/ | grep hugging
```

### Если `python -m` тоже не работает:
```dockerfile
# Попробовать прямой import в Python
RUN python << 'EOF'
from huggingface_hub import snapshot_download
import os

model_id = os.environ.get('MODEL_ID', 'THUDM/CogVideoX-5b-I2V')
cache_dir = '/model_cache'

print(f"Downloading model: {model_id}...")
snapshot_download(
    repo_id=model_id,
    cache_dir=cache_dir,
    ignore_patterns=['*.bin', '*.onnx', '*.pb', 'fp32/*']
)
print("✓ Model downloaded and cached")
EOF
```

---

## Контрольный чеклист

- [x] Обновлен `docker/Dockerfile.gen` с правильной командой
- [x] Обновлен `DOCKER_BUILD_TROUBLESHOOTING.md`
- [x] Обновлен `scripts/build_video_gen.sh`
- [ ] Очистить Docker cache: `docker builder prune -a -f`
- [ ] Пересобрать образ с `--no-cache`
- [ ] Верифицировать успешную сборку
- [ ] Протестировать CLI работоспособность
- [ ] Запустить dry-run тест

---

## Статус

**ИСПРАВЛЕНИЕ ПРИМЕНЕНО ✅**

Теперь команда использует:
```bash
python -m huggingface_hub.commands.huggingface_cli download ...
```

Это стандартный способ вызова HuggingFace CLI из Python модуля.

---

**ГОТОВО К СБОРКЕ! ПОПРОБУЙТЕ СНОВА! 🚀**

```bash
docker builder prune -a -f
docker build -f docker/Dockerfile.gen \
  -t registry.gitlab.com/gfever/vastai_interup:video-gen-020226 \
  --progress=plain \
  .
```
