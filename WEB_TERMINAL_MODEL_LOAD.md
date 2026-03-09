# 🚀 Загрузка моделей через Web Terminal

## Инструкция для быстрой загрузки моделей на Network Volume

### Шаг 1: Откройте Web Terminal
1. Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите pod `model-loader-temp` (ID: `nh700tlaxfjwgv`)
3. Нажмите **"Connect"** → **"Launch Web Terminal"**

### Шаг 2: Выполните команды в терминале

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
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False,
    resume_download=True
)
print('✅ DreamShaper загружен!')
"

# 4. Загрузите CogVideoX-5b-I2V (~15GB, 30-60 минут) В ФОНЕ
echo "📥 Загружаю CogVideoX (это займет 30-60 минут)..."
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
    resume_download=True
)
print('✅ CogVideoX загружен!')
" > /tmp/cog_download.log 2>&1 &

# 5. Мониторинг загрузки
echo "📊 Мониторинг загрузки CogVideoX:"
tail -f /tmp/cog_download.log
```

### Шаг 3: Проверьте загрузку (в другом окне терминала)

```bash
# Проверьте DreamShaper
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
# Должен быть: sdxl_lightning_4step_unet.safetensors (~2GB)

# Проверьте прогресс CogVideoX
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | wc -l
du -sh /runpod-volume/models/CogVideoX-5b-I2V/

# Общий размер
du -sh /runpod-volume/models/
```

### Шаг 4: После завершения загрузки

```bash
# 1. Убедитесь, что обе модели загружены
ls -la /runpod-volume/models/dreamshaper-xl-lightning/
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | head -20

# 2. Удалите pod-загрузчик (через RunPod Console)
# Или выполните:
# runpodctl remove pod nh700tlaxfjwgv
```

### Шаг 5: Запустите рабочий pod

```bash
# Создайте рабочий pod с легким образом
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

## Что происходит:
1. **Модели загружаются один раз** на Network Volume
2. **Pod-загрузчик удаляется** после завершения
3. **Рабочий pod запускается мгновенно** (образ ~6GB)
4. **Модели уже готовы** на подключенном томе

## Важные замечания:
- **Не закрывайте Web Terminal** во время загрузки CogVideoX
- **Используйте `Ctrl+C`** для остановки `tail -f`
- **Проверяйте место**: `df -h /runpod-volume`
- **Общий размер моделей**: ~17GB

## После загрузки моделей:
✅ DreamShaper: ~2GB
✅ CogVideoX: ~15GB
✅ Готово к использованию!

Пайплайн text2video будет работать сразу после запуска рабочего pod! 🎬