# 🎯 ФИНАЛЬНАЯ ИНСТРУКЦИЯ: Загрузка моделей через Web Terminal

## ✅ Pod готов к работе:
- **Имя**: `model-upload-terminal`
- **ID**: `9p630p7o41sol0`
- **Статус**: RUNNING
- **Образ**: `video-gen-serverless-v3` (6GB)
- **Network Volume**: подключен (`shrill_coral_herring`, 100GB)

## 🚀 Шаги для загрузки моделей:

### 1. Откройте Web Terminal:
1. Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите pod `model-upload-terminal` (ID: `9p630p7o41sol0`)
3. Нажмите **"Connect"** → **"Launch Web Terminal"**

### 2. В открывшемся терминале выполните команды:

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

# 4. Загрузите CogVideoX-5b-I2V (~15GB, 30-60 минут) В ФОНЕ
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

# 5. Мониторинг загрузки
echo "📊 Мониторинг загрузки CogVideoX:"
tail -f /tmp/cog_download.log
```

### 3. Проверка загрузки (в другом окне терминала):

```bash
# Проверьте DreamShaper
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
# Должен быть файл: sdxl_lightning_4step_unet.safetensors (~2GB)

# Проверьте прогресс CogVideoX
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | wc -l
du -sh /runpod-volume/models/CogVideoX-5b-I2V/

# Общий размер
du -sh /runpod-volume/models/
```

### 4. После завершения загрузки:

```bash
# 1. Убедитесь, что обе модели загружены
ls -la /runpod-volume/models/dreamshaper-xl-lightning/
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | head -20

# 2. Запустите handler вручную
cd /app
python -m src.entrypoints.runpod_handler

# Или перезапустите pod через RunPod Console
```

### 5. Тестирование пайплайна:

После запуска handler отправьте тестовый запрос:

```bash
# IP адрес pod можно найти в RunPod Console
curl -X POST http://<pod-ip>:8000/runsync \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "a beautiful sunset over mountains",
      "t2i_steps": 4,
      "num_inference_steps": 25,
      "num_frames": 16,
      "fps": 8
    }
  }'
```

## 📋 Что происходит:
1. **Web Terminal дает полный доступ** к работающему контейнеру
2. **Модели загружаются на Network Volume** (один раз)
3. **После загрузки** можно запустить handler или перезапустить pod
4. **Pайплайн готов** к генерации видео из текста

## ⚠️ Важные замечания:
- **Не закрывайте Web Terminal** во время загрузки CogVideoX
- **Используйте `Ctrl+C`** для остановки `tail -f`
- **Проверяйте свободное место**: `df -h /runpod-volume`
- **Общий размер моделей**: ~17GB

## 🎉 После успешной загрузки:
✅ DreamShaper: ~2GB
✅ CogVideoX: ~15GB
✅ Модели сохранены на Network Volume
✅ Можно запускать новые pods мгновенно

**Это финальный шаг!** После загрузки моделей через Web Terminal система будет полностью работоспособна. 🚀