# 🚀 Команда для быстрой загрузки моделей

## Pod готов к работе:
- **Имя**: `fast-model-downloader`
- **ID**: `afynhlyj6fiunk`
- **SSH порт**: `33303`
- **IP**: `213.173.102.167`

## Команда для подключения по SSH:
```bash
ssh afynhlyj6fiunk-33303@ssh.runpod.io -i ~/.ssh/id_ed25519
```

Или с указанием порта:
```bash
ssh -p 33303 afynhlyj6fiunk@213.173.102.167 -i ~/.ssh/id_ed25519
```

## После подключения выполните ОДНУ команду для загрузки моделей:

```bash
# Установите huggingface_hub и загрузите модели
pip install huggingface_hub && \
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning /runpod-volume/models/CogVideoX-5b-I2V && \
cd /runpod-volume/models/dreamshaper-xl-lightning && \
python3 -c "
from huggingface_hub import hf_hub_download
print('Загружаю DreamShaper...')
hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors', local_dir='.')
print('✅ DreamShaper загружен')
" && \
cd /runpod-volume/models/CogVideoX-5b-I2V && \
python3 -c "
from huggingface_hub import snapshot_download
print('Загружаю CogVideoX... (30-60 минут)')
snapshot_download('THUDM/CogVideoX-5b', local_dir='.', ignore_patterns=['*.bin', '*.msgpack'])
print('✅ CogVideoX загружен')
" > /tmp/download.log 2>&1 &
```

## Проверка загрузки:
```bash
# Проверьте DreamShaper
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/

# Проверьте прогресс CogVideoX
tail -f /tmp/download.log
```

## После загрузки моделей:
1. Модели будут на Network Volume
2. Удалите pod через RunPod Console
3. Запустите рабочий pod:

```bash
runpodctl create pod \
  --name "video-gen-ready" \
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

## Быстрая команда для копирования и вставки:
```bash
ssh afynhlyj6fiunk-33303@ssh.runpod.io -i ~/.ssh/id_ed25519 "pip install huggingface_hub && mkdir -p /runpod-volume/models/dreamshaper-xl-lightning /runpod-volume/models/CogVideoX-5b-I2V && cd /runpod-volume/models/dreamshaper-xl-lightning && python3 -c \"from huggingface_hub import hf_hub_download; print('Загружаю DreamShaper...'); hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors', local_dir='.'); print('✅ DreamShaper загружен')\" && cd /runpod-volume/models/CogVideoX-5b-I2V && python3 -c \"from huggingface_hub import snapshot_download; print('Загружаю CogVideoX...'); snapshot_download('THUDM/CogVideoX-5b', local_dir='.', ignore_patterns=['*.bin', '*.msgpack']); print('✅ CogVideoX загружен')\" > /tmp/download.log 2>&1 &"
```

**Pod готов! Подключайтесь по SSH и загружайте модели.** 🚀