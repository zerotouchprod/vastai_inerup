# 📥 Список команд для загрузки моделей из pod

## Подключение к pod:
```bash
ssh afynhlyj6fiunk-64410f82@ssh.runpod.io -i ~/.ssh/id_ed25519
```

## После подключения выполните команды по порядку:

### 1. Установите huggingface_hub:
```bash
pip install huggingface_hub
```

### 2. Создайте директории для моделей:
```bash
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V
```

### 3. Загрузите DreamShaper XL Lightning (~2GB, 5-10 минут):
```bash
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
print('Загружаю DreamShaper...')
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False,
    resume_download=True
)
print('✅ DreamShaper загружен!')
import os
size = os.path.getsize('sdxl_lightning_4step_unet.safetensors')
print(f'Размер: {size / (1024**3):.2f} GB')
"
```

### 4. Загрузите CogVideoX-5b-I2V (~15GB, 30-60 минут) В ФОНЕ:
```bash
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
import os
import time
print('Загружаю CogVideoX... (30-60 минут)')
start_time = time.time()
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
    resume_download=True
)
download_time = time.time() - start_time
files = [f for f in os.listdir('.') if os.path.isfile(f)]
total_size = sum(os.path.getsize(f) for f in files)
print('✅ CogVideoX загружен!')
print(f'Файлов: {len(files)}')
print(f'Общий размер: {total_size / (1024**3):.2f} GB')
print(f'Время загрузки: {download_time/60:.1f} минут')
" > /tmp/cog_download.log 2>&1 &
```

### 5. Мониторинг загрузки CogVideoX:
```bash
tail -f /tmp/cog_download.log
```

## Проверка загрузки:

### Проверьте DreamShaper:
```bash
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
# Должен быть: sdxl_lightning_4step_unet.safetensors (~2GB)
```

### Проверьте прогресс CogVideoX:
```bash
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | wc -l
du -sh /runpod-volume/models/CogVideoX-5b-I2V/
```

### Общий размер:
```bash
du -sh /runpod-volume/models/
```

## Одна команда для копирования и вставки (после подключения):
```bash
pip install huggingface_hub && mkdir -p /runpod-volume/models/dreamshaper-xl-lightning /runpod-volume/models/CogVideoX-5b-I2V && cd /runpod-volume/models/dreamshaper-xl-lightning && python3 -c "from huggingface_hub import hf_hub_download; print('Загружаю DreamShaper...'); hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors', local_dir='.'); print('✅ DreamShaper загружен')" && cd /runpod-volume/models/CogVideoX-5b-I2V && python3 -c "from huggingface_hub import snapshot_download; print('Загружаю CogVideoX...'); snapshot_download('THUDM/CogVideoX-5b', local_dir='.', ignore_patterns=['*.bin', '*.msgpack']); print('✅ CogVideoX загружен')" > /tmp/download.log 2>&1 &
```

## После загрузки моделей:

### 1. Убедитесь, что модели загружены:
```bash
ls -la /runpod-volume/models/dreamshaper-xl-lightning/
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | head -20
```

### 2. Удалите pod через RunPod Console (опционально)

### 3. Запустите рабочий pod:
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

## Важные замечания:
- **Не закрывайте SSH сессию** во время загрузки CogVideoX
- **Используйте `Ctrl+C`** для остановки `tail -f`
- **Проверяйте место**: `df -h /runpod-volume`
- **Общий размер моделей**: ~17GB

**Готово! После загрузки моделей пайплайн text2video будет работать.** 🚀