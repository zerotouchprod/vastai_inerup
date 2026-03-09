# ⏳ Ожидание запуска и тестирование

## Текущая ситуация:
✅ **Pod `video-gen-correct` создан** (ID: `oxy9ksf4y0fp4y`)
✅ **Используется правильный образ** (`video-gen-serverless`, 6GB без моделей)
⏳ **Образ загружается** (это нормально при первом запуске на хосте)

## Что происходит:
1. **RunPod загружает образ** на хост (3.5GB + 3.3GB + 4.6GB = ~11.5GB)
2. **После загрузки** образ будет закэширован на хосте
3. **Следующие pods** запустятся мгновенно (10-30 секунд)

## Время ожидания:
- **Загрузка образа**: 5-10 минут (зависит от скорости интернета)
- **Запуск pod**: 30-60 секунд после загрузки
- **Итого**: 6-12 минут

## Что делать после запуска:

### 1. Проверьте статус pod:
```bash
/tmp/runpodctl get pod oxy9ksf4y0fp4y -a
```

### 2. Когда статус станет RUNNING, проверьте логи:
- Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
- Найдите pod `video-gen-correct`
- Нажмите "Logs"

### 3. Ожидаемые логи:
```
✅ DreamShaper found: /runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors
✅ CogVideoX found: /runpod-volume/models/CogVideoX-5b-I2V
🚀 Starting RunPod handler...
```

### 4. Если модели не найдены:
Entrypoint выдаст ошибку и pod остановится. В этом случае:
- Проверьте через Web Terminal (см. `TEST_VOLUME_ACCESS.md`)
- Убедитесь, что Network Volume смонтирован

### 5. Тестирование API:
```bash
# Найдите IP адрес pod
/tmp/runpodctl get pod oxy9ksf4y0fp4y -a

# Отправьте тестовый запрос
curl -X POST http://<POD_IP>:8000/runsync \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "a beautiful sunset over mountains",
      "t2i_steps": 4,
      "num_inference_steps": 25
    }
  }'
```

## Преимущества после успешного запуска:
- 🚀 **Образ закэширован** на хосте RunPod
- 💰 **Следующие pods запустятся мгновенно**
- 🎬 **Pайплайн text2video готов к работе**
- 📈 **Масштабируемость**: Можно запускать множество pods

## Если pod не запускается:
1. Подождите 10-15 минут для загрузки образа
2. Проверьте логи в RunPod Console
3. Если ошибка "models not found" → проверьте Network Volume
4. Перезапустите pod (образ уже будет закэширован)

**Подождите 10-15 минут, затем проверьте статус и логи pod!** ⏳