# 🚀 Правильная команда для запуска pod БЕЗ загрузки моделей

## Проблема:
Используется образ `Dockerfile.serverless.with_models`, который загружает модели при сборке (25GB).

## Решение:
Использовать образ `Dockerfile.serverless` (6GB, без моделей).

## Правильная команда:

```bash
runpodctl create pod \
  --name "video-gen-fast" \
  --imageName "registry.gitlab.com/gfever/vastai_interup:video-gen-serverless" \
  --gpuType "NVIDIA GeForce RTX 4090" \
  --gpuCount 1 \
  --networkVolumeId "gwmcixcs3e" \
  --volumePath "/runpod-volume" \
  --ports "8000/http" \
  --containerDiskSize 20 \
  --volumeSize 100 \
  --secureCloud
```

**Обратите внимание на имя образа:**
- ❌ **Неправильно**: `video-gen-serverless-v3` (с моделями)
- ✅ **Правильно**: `video-gen-serverless` (без моделей)

## Что произойдет:
1. Pod запустится за **10-30 секунд** (образ 6GB)
2. Entrypoint проверит модели на Network Volume
3. Если модели найдены → запустит handler
4. Если модели не найдены → выдаст ошибку

## Проверка после запуска:

### 1. Удалите текущий pod (если нужно):
```bash
/tmp/runpodctl remove pod zgg2qo20fpdl8d
```

### 2. Запустите правильный pod:
```bash
runpodctl create pod \
  --name "video-gen-correct" \
  --imageName "registry.gitlab.com/gfever/vastai_interup:video-gen-serverless" \
  --gpuType "NVIDIA GeForce RTX 4090" \
  --gpuCount 1 \
  --networkVolumeId "gwmcixcs3e" \
  --volumePath "/runpod-volume" \
  --ports "8000/http" \
  --containerDiskSize 20 \
  --volumeSize 100 \
  --secureCloud
```

### 3. Проверьте логи:
- Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
- Найдите новый pod
- Нажмите "Logs"
- Должны увидеть: `✅ DreamShaper found` и `✅ CogVideoX found`

## Если образ `video-gen-serverless` не существует:
Нужно собрать его из `Dockerfile.serverless`:

```bash
# В директории проекта
docker build -f docker/Dockerfile.serverless -t registry.gitlab.com/gfever/vastai_interup:video-gen-serverless .
docker push registry.gitlab.com/gfever/vastai_interup:video-gen-serverless
```

## Альтернатива: использовать другой тег
Если образ с моделями уже закэширован, можно использовать его, но models будут игнорироваться:

```bash
runpodctl create pod \
  --name "video-gen-cached" \
  --imageName "registry.gitlab.com/gfever/vastai_interup:video-gen-serverless-v3" \
  --gpuType "NVIDIA GeForce RTX 4090" \
  --gpuCount 1 \
  --networkVolumeId "gwmcixcs3e" \
  --volumePath "/runpod-volume" \
  --ports "8000/http" \
  --containerDiskSize 20 \
  --volumeSize 100 \
  --secureCloud
```

**Запустите pod с правильным образом (без моделей)!** 🚀