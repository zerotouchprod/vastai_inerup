# 🔐 Загрузка моделей через SSH

## Подключение к pod для загрузки моделей

### SSH подключение:
```bash
ssh izrr0dqt3twapz-18551@ssh.runpod.io -i ~/.ssh/id_ed25519
```

Или с указанием порта:
```bash
ssh -p 18551 izrr0dqt3twapz@213.173.102.144 -i ~/.ssh/id_ed25519
```

### После подключения выполните команды:

```bash
# 1. Установите huggingface_hub
pip install huggingface_hub

# 2. Создайте директории для моделей
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# 3. Загрузите DreamShaper XL Lightning (~2GB, 5-10 минут)
echo "📥 Загружаю DreamShaper..."
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
print('Начинаю загрузку DreamShaper...')
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

# 4. Загрузите CogVideoX-5b-I2V (~15GB, 30-60 минут)
echo "📥 Загружаю CogVideoX (это займет 30-60 минут)..."
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
import os
import time
print('Начинаю загрузку CogVideoX...')
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

# 5. Мониторинг загрузки (в другом окне терминала)
echo "📊 Мониторинг загрузки CogVideoX:"
tail -f /tmp/cog_download.log
```

### Проверка загрузки:
```bash
# Проверьте DreamShaper
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/

# Проверьте прогресс CogVideoX
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | wc -l
du -sh /runpod-volume/models/CogVideoX-5b-I2V/

# Общий размер
du -sh /runpod-volume/models/
```

### После завершения загрузки:
1. Модели останутся на Network Volume
2. Pod можно удалить через RunPod Console
3. Запустите рабочий pod с легким образом

### Запуск рабочего pod:
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

## Важно:
- **SSH подключение работает**: Порт 18551 на 213.173.102.144
- **Pod активен**: Команда `sleep infinity` держит контейнер запущенным
- **Не закрывайте SSH сессию** во время загрузки CogVideoX
- **Используйте screen/tmux** для долгих операций