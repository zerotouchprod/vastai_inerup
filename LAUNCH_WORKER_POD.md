# 🚀 Запуск рабочего pod с моделями

## ✅ Модели успешно загружены:
- **DreamShaper**: 4.8GB (`sdxl_lightning_4step_unet.safetensors`)
- **CogVideoX**: 64 файла в директориях

## Команда для запуска рабочего pod:

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

## Что произойдет:
1. **Pod запустится за 10-30 секунд** (образ 6GB)
2. **Entrypoint проверит модели** на Network Volume
3. **Handler запустится автоматически** (модели найдены)
4. **API будет доступен** на порту 8000

## Проверка после запуска:

### 1. Найдите IP адрес pod:
```bash
/tmp/runpodctl get pod -a | grep video-gen-production
```

### 2. Отправьте тестовый запрос:
```bash
curl -X POST http://<POD_IP>:8000/runsync \
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

### 3. Проверьте логи в RunPod Console:
- Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
- Найдите pod `video-gen-production`
- Нажмите "Logs" для просмотра логов

## Удаление pod-загрузчика (опционально):
После запуска рабочего pod можно удалить pod-загрузчик:
```bash
/tmp/runpodctl remove pod afynhlyj6fiunk
```

Или через RunPod Console.

## Преимущества:
- 🚀 **Быстрый запуск**: 6GB vs 50GB с моделями
- 💰 **Экономия**: Не платим за трафик 44GB
- 🔄 **Гибкость**: Модели обновляются независимо
- 📈 **Масштабируемость**: Один Network Volume → множество pods

**Запускайте рабочий pod и тестируйте пайплайн text2video!** 🎬