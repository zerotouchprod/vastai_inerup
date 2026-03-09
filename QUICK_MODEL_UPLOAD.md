# 🚀 Быстрая загрузка моделей через Web Terminal

## Текущая ситуация
✅ **Pod работает**: `video-gen-fixed` (ID: `bc9a7u2pqlmoao`)
✅ **Entrypoint исправлен**: Проверяет наличие моделей
❌ **Модели отсутствуют**: Нужно загрузить на сетевой том

## Как загрузить модели:

### Шаг 1: Откройте Web Terminal
1. Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите pod `video-gen-fixed` (ID: `bc9a7u2pqlmoao`)
3. Нажмите **"Connect"** → **"Launch Web Terminal"**

### Шаг 2: Выполните команды в терминале

```bash
# 1. Установите huggingface_hub
pip install huggingface_hub

# 2. Создайте директории для моделей
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# 3. Загрузите DreamShaper XL Lightning (~2GB, 5-10 минут)
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
print('📥 Загружаю DreamShaper XL Lightning...')
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False
)
print('✅ DreamShaper загружен!')
"

# 4. Загрузите CogVideoX-5b-I2V (~15GB, 30-60 минут) В ФОНЕ
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
print('📥 Начинаю загрузку CogVideoX-5b-I2V...')
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

### Шаг 3: Проверьте загрузку
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

### Шаг 4: Перезапустите handler
После загрузки моделей:
```bash
# Убейте текущий процесс (он перезапустится автоматически)
pkill -f "python -m src.entrypoints.runpod_handler"

# Или перезапустите весь pod через RunPod Console
# Нажмите "Stop", затем "Start" на pod
```

## Альтернативный способ: Используйте готовый скрипт
Если можете отправить файл на pod:

```bash
# На локальной машине
runpodctl send upload_models_to_volume.py bc9a7u2pqlmoao:/root/

# В Web Terminal pod
cd /root
python3 upload_models_to_volume.py
```

## Что происходит после загрузки моделей:
1. Entrypoint скрипт обнаружит модели
2. Проверит GPU доступность
3. Запустит RunPod Serverless Handler
4. Endpoint будет готов принимать запросы на генерацию видео

## Тестовый запрос после загрузки:
```bash
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

## Важно:
- **Не закрывайте Web Terminal** во время загрузки CogVideoX
- **Проверяйте место на томе**: `df -h /runpod-volume`
- **Используйте `Ctrl+C`** для остановки `tail -f`
- **Для возобновления** прерванной загрузки используйте `resume_download=True`

После загрузки моделей пайплайн text2video будет полностью работоспособен! 🎬