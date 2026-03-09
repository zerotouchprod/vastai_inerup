# Инструкция по загрузке моделей на RunPod Network Volume

## Текущее состояние
- **Pod ID**: `3g474awleozkup` (video-gen-endpoint)
- **Образ**: `registry.gitlab.com/gfever/vastai_interup:video-gen-serverless-v2`
- **Сетевой том**: `shrill_coral_herring` (ID: `gwmcixcs3e`)
- **Путь монтирования**: `/runpod-volume`
- **Статус**: Pod запущен, но модели отсутствуют на томе

## Как загрузить модели

### Способ 1: Через Web Terminal RunPod
1. Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите pod `video-gen-endpoint` (ID: `3g474awleozkup`)
3. Нажмите "Connect" → "Launch Web Terminal"
4. В терминале выполните команды:

```bash
# Установите huggingface_hub
pip install huggingface_hub

# Создайте директории для моделей
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# Загрузите DreamShaper XL Lightning
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors', local_dir='.')
print('✅ DreamShaper загружен')
"

# Загрузите CogVideoX-5b-I2V (это займет 30-60 минут)
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('THUDM/CogVideoX-5b', local_dir='.', ignore_patterns=['*.bin', '*.msgpack'])
print('✅ CogVideoX загружен')
" > /tmp/cog_download.log 2>&1 &

# Мониторинг загрузки
tail -f /tmp/cog_download.log
```

### Способ 2: Через отдельный pod для загрузки
Если текущий pod не имеет доступа к интернету или есть проблемы с загрузкой:

1. Создайте временный pod для загрузки:
```bash
runpodctl create pod \
  --name "model-downloader" \
  --imageName "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime" \
  --gpuType "NVIDIA GeForce RTX 4090" \
  --gpuCount 1 \
  --ports "22/tcp" \
  --containerDiskSize 50 \
  --volumeSize 100 \
  --secureCloud \
  --networkVolumeId "gwmcixcs3e" \
  --volumePath "/runpod-volume"
```

2. Выполните команды загрузки из Способа 1

### Способ 3: Используйте готовый скрипт
На локальной машине:
```bash
# Отправьте скрипт на pod (если SSH работает)
runpodctl send upload_models_to_volume.py 3g474awleozkup:/root/

# Выполните скрипт
runpodctl exec python --pod_id 3g474awleozkup -- "python /root/upload_models_to_volume.py"
```

## Проверка загрузки моделей
После загрузки проверьте наличие моделей:

```bash
# Проверьте DreamShaper
ls -la /runpod-volume/models/dreamshaper-xl-lightning/
# Должен быть файл: sdxl_lightning_4step_unet.safetensors (~2GB)

# Проверьте CogVideoX
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ | head -20
# Должно быть много файлов, общий размер ~15GB

# Проверьте общий размер
du -sh /runpod-volume/models/
```

## Перезапуск handler
После загрузки моделей перезапустите pod или дождитесь автоматического перезапуска handler:

```bash
# Внутри pod перезапустите entrypoint
pkill -f "python -m src.entrypoints.runpod_handler"
# Или перезапустите весь pod через RunPod Console
```

## Тестирование пайплайна
После загрузки моделей протестируйте генерацию:

1. Отправьте тестовый запрос на endpoint
2. Используйте пример из `test_job.json`:
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

## Важные замечания
1. **Размер моделей**: 
   - DreamShaper: ~2GB
   - CogVideoX: ~15GB
   - Общий: ~17GB

2. **Время загрузки**:
   - DreamShaper: 5-10 минут
   - CogVideoX: 30-60 минут (зависит от скорости интернета)

3. **Объем тома**: Сетевой том имеет 100GB, места достаточно.

4. **Автоматическая проверка**: Entrypoint скрипт автоматически проверяет наличие моделей при запуске и выдает понятные ошибки, если модели отсутствуют.

## Устранение неполадок
Если models не загружаются:
1. Проверьте доступ к huggingface.co
2. Убедитесь, что том смонтирован правильно
3. Проверьте доступное место на томе: `df -h /runpod-volume`
4. Используйте `--resume_download=True` для возобновления прерванной загрузки