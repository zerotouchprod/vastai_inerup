# RunPod Serverless Deployment Guide

## 📋 Обзор

Это руководство описывает развертывание пайплайна генерации видео на RunPod Serverless. Вместо 50GB Docker образа мы используем:
- **Легкий Docker образ** (~6GB) с зависимостями
- **Сетевой том RunPod** для хранения моделей (100GB)
- **Serverless функцию** для обработки запросов

## 🚀 Быстрый старт

### 1. Предварительные требования
- Аккаунт RunPod с API ключом
- Минимум $10 на балансе
- Доступ к GitHub Container Registry (опционально)

### 2. Шаги развертывания

#### Шаг 1: Создание сетевого тома
1. Перейдите в [RunPod Storage Console](https://www.runpod.io/console/user/storage)
2. Нажмите "Create Network Volume"
3. Настройки:
   - **Name**: `video-gen-models`
   - **Size**: 100 GB
   - **Data Center**: Любой с RTX 4090
4. Запишите **Volume ID**

#### Шаг 2: Загрузка моделей на том
1. Создайте временный pod:
   ```bash
   # Используйте RunPod CLI или веб-интерфейс
   runpodctl pod create \
     --name "model-downloader" \
     --image pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime \
     --gpu-type "RTX 4090" \
     --volume <VOLUME_ID>:/runpod-volume \
     --env "HF_TOKEN=<your-huggingface-token>"
   ```

2. Подключитесь к pod и выполните:
   ```bash
   # Клонируйте репозиторий
   git clone https://github.com/zerotouchprod/vastai_inerup.git
   cd vastai_inerup
   
   # Загрузите модели
   python scripts/prep_runpod_volume.py \
     --volume-path /runpod-volume/models \
     --model all
   ```

3. Удалите временный pod после загрузки

#### Шаг 3: Сборка Docker образа
```bash
# Клонируйте репозиторий
git clone https://github.com/zerotouchprod/vastai_inerup.git
cd vastai_inerup

# Соберите образ
docker build -f docker/Dockerfile.serverless -t vastai-video-gen-serverless:latest .

# Запушьте в реестр (пример для GitHub Container Registry)
docker tag vastai-video-gen-serverless:latest ghcr.io/zerotouchprod/vastai-video-gen-serverless:latest
docker push ghcr.io/zerotouchprod/vastai-video-gen-serverless:latest
```

#### Шаг 4: Создание Serverless функции
1. Перейдите в [RunPod Serverless Console](https://www.runpod.io/console/serverless)
2. Нажмите "Create New Endpoint"
3. Настройки:
   - **Name**: `video-generation-endpoint`
   - **Container Image**: `ghcr.io/zerotouchprod/vastai-video-gen-serverless:latest`
   - **GPU Type**: `NVIDIA RTX 4090`
   - **Idle Timeout**: 5 минут
   - **Max Workers**: 1
   - **Flashboot**: Включено
   - **Container Disk**: 10 GB
4. Примонтируйте сетевой том:
   - **Volume ID**: `<your-volume-id>`
   - **Mount Path**: `/runpod-volume`

#### Шаг 5: Тестирование
```python
import runpod
import os

# Настройте API ключ из переменной окружения
runpod.api_key = os.environ.get("RUNPOD_API_KEY", "your-api-key-here")

# ID вашей endpoint функции
endpoint_id = "<your-endpoint-id>"

# Тестовый запрос
test_input = {
    "prompt": "A beautiful sunset over mountains, cinematic, 4k",
    "t2i_steps": 8,
    "t2i_guidance_scale": 3.5,
    "num_inference_steps": 25,
    "guidance_scale": 6.0,
    "num_frames": 16,
    "fps": 8,
    "seed": 42
}

# Запуск job
job = runpod.run(endpoint_id, test_input)
print(f"Job ID: {job['id']}")

# Проверка статуса
status = runpod.get_job_status(endpoint_id, job['id'])
print(f"Status: {status}")

# Получение результата
result = runpod.get_job_result(endpoint_id, job['id'])
print(f"Result: {result}")
```

## 📁 Структура проекта

### Docker образ (`docker/Dockerfile.serverless`)
```dockerfile
# Легкий образ (~6GB) с:
# - PyTorch 2.5.1 + CUDA 12.4
# - Зависимости из requirements.gen.txt
# - RunPod SDK
# - Код приложения
# БЕЗ моделей (хранятся на сетевом томе)
```

### Serverless handler (`src/entrypoints/runpod_handler.py`)
```python
# Основной обработчик:
# 1. Загружает модели с /runpod-volume/models/
# 2. Генерирует изображение (T2I)
# 3. Очищает VRAM
# 4. Генерирует видео (I2V)
# 5. Загружает результат в B2/S3
# 6. Возвращает URL
```

### Скрипты
- `scripts/prep_runpod_volume.py` - загрузка моделей на том
- `scripts/runpod_manager.py` - управление развертыванием
- `test_runpod.py` - тестирование endpoint

## ⚙️ Конфигурация

### Параметры генерации
```json
{
  "prompt": "строка, обязательный",
  "negative_prompt": "строка, опциональный",
  "t2i_steps": "число, шаги T2I (по умолчанию: 4)",
  "t2i_guidance_scale": "число, guidance T2I (по умолчанию: 0.0)",
  "num_inference_steps": "число, шаги I2V (по умолчанию: 25)",
  "guidance_scale": "число, guidance I2V (по умолчанию: 6.0)",
  "num_frames": "число, кадры (по умолчанию: 16)",
  "fps": "число, FPS (по умолчанию: 8)",
  "seed": "число, сид для воспроизводимости"
}
```

### Переменные окружения
```bash
# В RunPod endpoint settings:
RUNPOD_API_KEY=your-api-key
ENABLE_SAFETY_CHECKER=False
B2_APPLICATION_KEY_ID=your-b2-key-id
B2_APPLICATION_KEY=your-b2-key
B2_BUCKET_NAME=your-bucket
```

## 💰 Стоимость

### Оценка затрат
- **Сетевой том**: $0.50/GB/месяц (100GB = $50/месяц)
- **Serverless функция**: $0.0002/секунда GPU ($0.72/час)
- **Хранение результатов**: $0.005/GB/месяц (B2)

### Пример расчета
- Генерация 1 видео: ~300 секунд = $0.06
- 1000 видео/месяц: $60 + $50 (том) = $110/месяц

## 🔧 Устранение неполадок

### Общие проблемы

#### 1. Модели не загружаются
```bash
# Проверьте монтирование тома
ls -la /runpod-volume/models/

# Проверьте наличие моделей
ls -la /runpod-volume/models/dreamshaper-xl-lightning/
ls -la /runpod-volume/models/CogVideoX-5b-I2V/
```

#### 2. Недостаточно VRAM
- Уменьшите `num_frames` (16 вместо 49)
- Уменьшите `num_inference_steps` (25 вместо 50)
- Используйте `enable_vae_slicing()` и `enable_vae_tiling()`

#### 3. Медленная генерация
- Используйте `torch.bfloat16` вместо `torch.float32`
- Включите `xformers` для оптимизации
- Используйте `flash_attention` если доступно

#### 4. Ошибки загрузки в B2
```python
# Проверьте переменные окружения
import os
print("B2_KEY_ID:", os.environ.get("B2_APPLICATION_KEY_ID"))
print("B2_KEY:", os.environ.get("B2_APPLICATION_KEY")[:10] + "...")
```

### Мониторинг
1. **Логи RunPod**: Console → Serverless → Endpoint → Logs
2. **Метрики GPU**: Console → Serverless → Endpoint → Metrics
3. **Баланс**: Console → User → Billing

## 📈 Оптимизация производительности

### Для продакшена
1. **Кэширование моделей**: Модели остаются загруженными между запросами
2. **Warm workers**: Настройте `minWorkers: 1` для быстрого старта
3. **Оптимизация VRAM**: Используйте `torch.inference_mode()` и `gc.collect()`

### Для качества
1. **Увеличьте шаги**: `t2i_steps: 8`, `num_inference_steps: 50`
2. **Увеличьте кадры**: `num_frames: 49` для 6-секундного видео
3. **Используйте детальные промпты**: Добавьте стили и детали

## 🔄 Обновление

### Обновление кода
```bash
# 1. Обновите код
git pull origin main_video_gen

# 2. Пересоберите образ
docker build -f docker/Dockerfile.serverless -t vastai-video-gen-serverless:latest .

# 3. Запушьте в реестр
docker push ghcr.io/zerotouchprod/vastai-video-gen-serverless:latest

# 4. Обновите endpoint в RunPod Console
```

### Обновление моделей
1. Создайте новый сетевой том
2. Загрузите обновленные модели
3. Обновите endpoint для использования нового тома
4. Удалите старый том

## 📞 Поддержка

### Полезные ссылки
- [RunPod Documentation](https://docs.runpod.io/)
- [GitHub Repository](https://github.com/zerotouchprod/vastai_inerup)
- [Dockerfile Reference](docker/Dockerfile.serverless)

### Контакты
- **Issues**: [GitHub Issues](https://github.com/zerotouchprod/vastai_inerup/issues)
- **Discord**: RunPod Community Discord

---

## ✅ Чеклист развертывания

- [ ] Создан сетевой том (100GB)
- [ ] Модели загружены на том
- [ ] Docker образ собран и запушен
- [ ] Serverless endpoint создан
- [ ] Том примонтирован к endpoint
- [ ] Переменные окружения настроены
- [ ] Тестовый запрос выполнен успешно
- [ ] Баланс пополнен (> $10)

---

**Версия**: 1.0.0  
**Дата**: 2026-03-05  
**Статус**: Готово к развертыванию