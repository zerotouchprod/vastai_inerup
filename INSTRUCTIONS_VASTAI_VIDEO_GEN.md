# Инструкция по запуску пайплайна text2image image2video на Vast AI

## Обзор

Это руководство описывает как запустить Docker образ `registry.gitlab.com/gfever/vastai_interup:video-gen` на Vast AI и выполнить пайплайн text2image image2video используя существующий код в `src/entrypoints/run_gen.py`.

## Предварительные требования

1. **Аккаунт на Vast AI**: https://vast.ai/
2. **API ключ Vast AI**: Получите из настроек аккаунта
3. **Docker образ**: `registry.gitlab.com/gfever/vastai_interup:video-gen` (уже собран)
4. **B2/S3 хранилище** (опционально): Для загрузки результатов

## Настройка окружения

### 1. Установите переменные окружения

```bash
# API ключ Vast AI (обязательно)
export VAST_API_KEY="ваш_api_ключ_здесь"

# B2/S3 credentials (опционально, для загрузки результатов)
export B2_KEY="ваш_b2_key_id"
export B2_SECRET="ваш_b2_application_key"
export B2_BUCKET="ваш_bucket_name"
export B2_ENDPOINT="https://s3.us-east-005.backblazeb2.com"  # пример
export B2_REGION="us-east-005"  # пример
```

### 2. Проверьте доступность Docker образа

Образ `registry.gitlab.com/gfever/vastai_interup:video-gen` должен быть доступен в Docker registry. Если нет, можно собрать его локально:

```bash
# Сборка образа из Dockerfile.universal_no_token
cd /workspace/vastai_inerup
./scripts/build_universal_no_token.sh

# Или сборка video-gen образа
./scripts/build_video_gen.sh
```

## Запуск пайплайна

### Способ 1: Использование готового скрипта `run_video_gen_vastai.py`

```bash
cd /workspace/vastai_inerup

# Text-to-Video с одним промптом
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "A cat dancing in the rain, cinematic, 4k"

# Text-to-Video с несколькими промптами
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "Sunset over ocean" "City at night" "Forest with animals" \
  --num-frames 64 \
  --guidance-scale 7.5 \
  --seed 42

# Image-to-Video (требует URL изображений)
python run_video_gen_vastai.py \
  --mode image2video \
  --prompts "Make the character dance" "Add fire effects" \
  --input-images "https://example.com/character1.jpg" "https://example.com/character2.jpg" \
  --num-frames 49 \
  --fps 8
```

### Способ 2: Ручной запуск через `vast_submit.py`

```bash
cd /workspace/vastai_inerup

# Создайте JSON задание
JOB_JSON='{
  "mode": "text2video",
  "prompts": ["Cyberpunk city at night, rain, neon lights"],
  "guidance_scale": 7.5,
  "num_inference_steps": 30,
  "num_frames": 49,
  "fps": 8,
  "output_prefix": "vastai_generation/"
}'

# Запустите на Vast AI
python vast/vast_submit.py \
  --image "registry.gitlab.com/gfever/vastai_interup:video-gen" \
  --cmd "python -m src.entrypoints.run_gen --job '$JOB_JSON'" \
  --min-vram 24 \
  --max-price 1.0
```

### Способ 3: Использование конкретного оффера на Vast AI

```bash
# Найдите подходящий оффер
python vast/vast_submit.py --search-only --min-vram 24 --max-price 1.0

# Используйте ID оффера для запуска
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "Test generation" \
  --offer-id 123456 \
  --offline
```

## Параметры пайплайна

### Основные параметры:
- `--mode`: `text2video` или `image2video`
- `--prompts`: Один или несколько текстовых промптов
- `--input-images`: URL изображений (только для `image2video`)

### Параметры генерации:
- `--num-frames`: Количество кадров (по умолчанию: 49)
- `--fps`: FPS выходного видео (по умолчанию: 8)
- `--guidance-scale`: Коэффициент guidance (по умолчанию: 7.5)
- `--num-inference-steps`: Шаги инференса (по умолчанию: 30)
- `--seed`: Сид для воспроизводимости
- `--negative-prompt`: Негативный промпт

### Параметры Vast AI:
- `--min-vram`: Минимальный VRAM в GB (по умолчанию: 24)
- `--max-price`: Максимальная цена в USD/час (по умолчанию: 1.0)
- `--image`: Docker образ (по умолчанию: registry.gitlab.com/gfever/vastai_interup:video-gen)

## Примеры использования

### Пример 1: Быстрый тест
```bash
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "A simple test" \
  --num-frames 16 \
  --no-upload
```

### Пример 2: Производственная генерация
```bash
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "Cinematic shot of a spaceship landing on Mars, dust clouds, realistic, 4k" \
  --num-frames 64 \
  --guidance-scale 8.0 \
  --num-inference-steps 50 \
  --seed 12345 \
  --min-vram 32 \
  --max-price 2.0
```

### Пример 3: Пакетная обработка
```bash
python run_video_gen_vastai.py \
  --mode text2video \
  --prompts "Scene 1: Sunrise over mountains" "Scene 2: Waterfall in forest" "Scene 3: Night sky with stars" \
  --output-prefix "nature_scenes/" \
  --num-frames 32 \
  --fps 12
```

## Мониторинг и результаты

### Мониторинг инстанса:
1. Залогиньтесь на https://vast.ai/
2. Перейдите в раздел "Instances"
3. Найдите ваш запущенный инстанс
4. Просматривайте логи в реальном времени

### Результаты:
- Видео генерируются в контейнере
- Загружаются в B2/S3 хранилище (если настроено)
- URL результатов выводятся в JSON формате
- Локальные файлы удаляются после загрузки

### Формат вывода:
```json
{
  "job_id": "uuid",
  "success": true,
  "total_prompts": 3,
  "successful": 3,
  "failed": 0,
  "duration_seconds": 125.5,
  "results": [
    {
      "prompt_index": 0,
      "prompt": "A cat dancing...",
      "output_key": "vastai_generation/uuid_0.mp4",
      "url": "https://bucket.s3.region.amazonaws.com/vastai_generation/uuid_0.mp4",
      "size_bytes": 10485760,
      "success": true,
      "error": null
    }
  ]
}
```

## Устранение неполадок

### 1. Ошибка аутентификации Vast AI
```
Error: VAST_API_KEY environment variable is not set
```
**Решение:** Установите переменную окружения `VAST_API_KEY`

### 2. Недостаточно VRAM
```
No offers found with min_vram=24
```
**Решение:** Уменьшите `--min-vram` или увеличьте `--max-price`

### 3. Ошибка загрузки модели
```
Failed to download model: Connection error
```
**Решение:** Образ уже содержит модели, но если есть проблемы с сетью, попробуйте другой инстанс

### 4. Таймаут генерации
```
Generation timed out after 300 seconds
```
**Решение:** Увеличьте время выполнения или уменьшите `--num-frames`

### 5. Проблемы с B2 загрузкой
```
B2 client unavailable: Missing credentials
```
**Решение:** Настройте B2 credentials или используйте `--no-upload`

## Оптимизация затрат

1. **Выбор GPU**: RTX 3090/4090 имеют лучшую производительность/цену
2. **Время аренды**: Генерация одного видео занимает 2-10 минут
3. **Пакетная обработка**: Генерация нескольких видео за одну аренду снижает стоимость
4. **Настройка параметров**: Уменьшение `--num-frames` и `--num-inference-steps` ускоряет генерацию

## Безопасность

1. **API ключи**: Никогда не коммитьте API ключи в репозиторий
2. **Docker образ**: Используйте официальный образ или собирайте свой
3. **Данные**: Результаты загружаются в ваше приватное хранилище
4. **Очистка**: Временные файлы удаляются после завершения

## Дополнительные ресурсы

1. **Документация Vast AI**: https://vast.ai/docs/
2. **Dockerfile**: `docker/Dockerfile.universal_no_token`
3. **Код пайплайна**: `src/entrypoints/run_gen.py`
4. **Код для Vast AI**: `vast/vast_submit.py`
5. **Примеры конфигурации**: `config.yaml`

## Поддержка

При возникновении проблем:
1. Проверьте логи инстанса на Vast AI
2. Убедитесь что все переменные окружения установлены
3. Проверьте доступность Docker образа
4. Обратитесь к документации проекта

---

**Примечание**: Для первого запуска рекомендуется начать с тестового промпта и минимальных параметров для проверки работоспособности системы.