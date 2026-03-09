# 🎯 ФИНАЛЬНЫЕ ИНСТРУКЦИИ: Запуск RunPod пайплайна text2video

## 📋 Краткое резюме
✅ **Архитектура настроена**: Легкий образ (6GB) + модели на Network Volume (100GB)
✅ **Pod для загрузки готов**: `model-loader-temp` (ID: `nh700tlaxfjwgv`)
✅ **Документация создана**: Пошаговые инструкции ниже

## 🚀 3 ШАГА ДЛЯ ЗАПУСКА:

### ШАГ 1: Загрузите модели на Network Volume (один раз)
1. Откройте [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите pod `model-loader-temp` (ID: `nh700tlaxfjwgv`)
3. Нажмите **"Connect"** → **"Launch Web Terminal"**
4. Выполните команды:

```bash
# Установите huggingface_hub
pip install huggingface_hub

# Создайте директории
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# Загрузите DreamShaper (5-10 минут)
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors', local_dir='.')
print('✅ DreamShaper загружен')
"

# Загрузите CogVideoX (30-60 минут, в фоне)
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('THUDM/CogVideoX-5b', local_dir='.', ignore_patterns=['*.bin', '*.msgpack'])
print('✅ CogVideoX загружен')
" > /tmp/cog.log 2>&1 &

# Мониторинг
tail -f /tmp/cog.log
```

### ШАГ 2: После загрузки моделей
1. Убедитесь, что модели загружены:
```bash
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
du -sh /runpod-volume/models/CogVideoX-5b-I2V/
```

2. Удалите pod-загрузчик через RunPod Console (или оставьте, если хотите)

### ШАГ 3: Запустите рабочий pod
```bash
runpodctl create pod \
  --name "video-gen-production" \
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

## 🎬 Тестирование пайплайна
После запуска рабочего pod отправьте тестовый запрос:

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

## 📊 Преимущества этой архитектуры:
- **🚀 Быстрый запуск**: 6GB образ vs 50GB
- **💰 Экономия**: Не платим за загрузку 44GB каждый раз
- **🔄 Гибкость**: Модели можно обновлять без пересборки образа
- **📈 Масштабирование**: Один Network Volume → множество pods

## 🛠️ Полезные команды:
```bash
# Проверить статус pods
/tmp/runpodctl get pod -a

# Удалить pod
/tmp/runpodctl remove pod <pod_id>

# Проверить баланс
/tmp/runpodctl config show
```

## 🆘 Устранение неполадок:
1. **Модели не загружаются**: Проверьте интернет-соединение в pod
2. **Не хватает места**: `df -h /runpod-volume` (должно быть > 50GB свободно)
3. **Pod не запускается**: Проверьте логи в RunPod Console → "Logs"

## 🎉 Готово!
После загрузки моделей на Network Volume вы сможете запускать pods мгновенно и использовать пайплайн text2video для генерации видео из текста.

**Время загрузки моделей**: 30-60 минут (один раз)
**Время запуска pod после загрузки**: 10-30 секунд (каждый раз)

Удачи! 🚀