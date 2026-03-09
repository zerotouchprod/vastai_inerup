# 🔍 Проверка и исправление загрузки моделей

## Текущая ситуация:
✅ **CogVideoX загружен**, но размер 0.00 GB (возможно, симлинки)
❌ **DreamShaper еще не загружен**

## Команды для проверки и исправления:

### 1. Проверьте, что загрузилось:
```bash
# Проверьте CogVideoX файлы
ls -la /runpod-volume/models/CogVideoX-5b-I2V/
ls -lh /runpod-volume/models/CogVideoX-5b-I2V/

# Проверьте, являются ли файлы симлинками
find /runpod-volume/models/CogVideoX-5b-I2V/ -type l -ls

# Проверьте реальный размер
du -sh /runpod-volume/models/CogVideoX-5b-I2V/ --apparent-size
du -sh /runpod-volume/models/CogVideoX-5b-I2V/
```

### 2. Если файлы симлинки, загрузите реальные файлы:
```bash
# Удалите симлинки и загрузите реальные файлы
cd /runpod-volume/models/CogVideoX-5b-I2V
rm -rf *
python3 -c "
from huggingface_hub import snapshot_download
import os
print('Загружаю CogVideoX с реальными файлами...')
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot']
)
print('✅ CogVideoX загружен с реальными файлами')
"
```

### 3. Загрузите DreamShaper:
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
if os.path.exists('sdxl_lightning_4step_unet.safetensors'):
    size = os.path.getsize('sdxl_lightning_4step_unet.safetensors')
    print(f'Размер: {size / (1024**3):.2f} GB')
else:
    print('❌ Файл не найден')
"
```

### 4. Проверьте обе модели:
```bash
echo "=== DreamShaper ==="
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
if [ -f "/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors" ]; then
    size=$(stat -c%s "/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors")
    echo "✅ DreamShaper: $(echo "scale=2; $size/1024/1024/1024" | bc) GB"
else
    echo "❌ DreamShaper не найден"
fi

echo ""
echo "=== CogVideoX ==="
ls -lh /runpod-volume/models/CogVideoX-5b-I2V/ | head -20
total_size=$(find /runpod-volume/models/CogVideoX-5b-I2V/ -type f -exec stat -c%s {} + | awk '{sum+=$1} END {print sum}')
echo "✅ CogVideoX: $(echo "scale=2; $total_size/1024/1024/1024" | bc) GB"
echo "Файлов: $(find /runpod-volume/models/CogVideoX-5b-I2V/ -type f | wc -l)"
```

### 5. Если DreamShaper не загружается, попробуйте альтернативный репозиторий:
```bash
cd /runpod-volume/models/dreamshaper-xl-lightning
rm -rf *
python3 -c "
from huggingface_hub import hf_hub_download
print('Пробую альтернативный репозиторий...')
try:
    hf_hub_download(
        repo_id='Lykon/dreamshaper-xl-lightning',
        filename='dreamshaperXL_lightningDPMSDE.safetensors',
        local_dir='.',
        local_dir_use_symlinks=False
    )
    print('✅ DreamShaper загружен из Lykon/dreamshaper-xl-lightning')
except Exception as e:
    print(f'❌ Ошибка: {e}')
    print('Пробую другой файл...')
    hf_hub_download(
        repo_id='ByteDance/SDXL-Lightning',
        filename='sdxl_lightning_4step_unet.safetensors',
        local_dir='.',
        local_dir_use_symlinks=False
    )
    print('✅ DreamShaper загружен из ByteDance/SDXL-Lightning')
"
```

### 6. После успешной загрузки проверьте entrypoint:
```bash
# Запустите проверку entrypoint
cd /app
python3 -c "
import os
t2i_path = '/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors'
i2v_path = '/runpod-volume/models/CogVideoX-5b-I2V'

if os.path.exists(t2i_path):
    print(f'✅ DreamShaper найден: {t2i_path}')
    print(f'   Размер: {os.path.getsize(t2i_path) / (1024**3):.2f} GB')
else:
    print(f'❌ DreamShaper не найден: {t2i_path}')

if os.path.exists(i2v_path):
    files = [f for f in os.listdir(i2v_path) if os.path.isfile(os.path.join(i2v_path, f))]
    print(f'✅ CogVideoX найден: {i2v_path}')
    print(f'   Файлов: {len(files)}')
else:
    print(f'❌ CogVideoX не найден: {i2v_path}')
"
```

## Что делать если модели загружены:
1. Удалите pod-загрузчик через RunPod Console
2. Запустите рабочий pod:

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

**Выполните команды по порядку для проверки и исправления загрузки моделей.** 🔧