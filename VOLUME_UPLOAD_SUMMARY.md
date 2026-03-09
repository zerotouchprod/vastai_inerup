# Загрузка моделей на RunPod том `shrill_coral_herring` - Итоговый отчет

## ✅ Выполнено

### 1. Созданы скрипты для загрузки моделей
- **`upload_models_api.sh`** - автоматический скрипт загрузки через API
- **`upload_models_simple.py`** - инструкции и команды для ручной загрузки
- **`check_volume.sh`** - скрипт проверки содержимого тома
- **`MODEL_UPLOAD_INSTRUCTIONS.md`** - полное руководство

### 2. Подготовлена инфраструктура
- API ключ RunPod проверен (работает)
- Сетевой том `shrill_coral_herring` указан как целевой
- Созданы команды для управления через GraphQL API

### 3. Определены модели для загрузки
| Модель | Репозиторий | Размер | Назначение |
|--------|-------------|--------|------------|
| DreamShaper XL Lightning | `ByteDance/SDXL-Lightning` | ~6.5GB | Text-to-Image |
| CogVideoX-5b | `THUDM/CogVideoX-5b` | ~18GB | Image-to-Video |
| **Итого** | - | **~24.5GB** | Полный пайплайн |

## 🚀 Как загрузить модели

### Быстрый способ (рекомендуется):
```bash
# 1. Установите API ключ
export RUNPOD_API_KEY="ваш_api_ключ"

# 2. Сделайте скрипты исполняемыми
chmod +x upload_models_api.sh check_volume.sh

# 3. Загрузите модели
./upload_models_api.sh

# 4. Проверьте результат
./check_volume.sh
```

### Ручной способ:
1. Найдите ID тома через API
2. Создайте временный pod с томом
3. Подключитесь по SSH
4. Загрузите модели командами из инструкций

## 📊 Ожидаемая структура после загрузки

```
/runpod-volume/models/
├── dreamshaper-xl-lightning/
│   └── sdxl_lightning_4step_unet.safetensors  (6.5GB)
└── CogVideoX-5b-I2V/
    ├── diffusion_pytorch_model.safetensors     (18GB)
    ├── config.json
    └── ... другие файлы модели
```

## ⏱️ Время и стоимость

### Время загрузки:
- **DreamShaper**: 5-15 минут
- **CogVideoX**: 30-60 минут  
- **Итого**: 35-75 минут

### Стоимость:
- **Pod (RTX 4090, 1 час)**: $0.70-$1.20
- **Том (100GB)**: $50/месяц
- **Итого за загрузку**: ~$1.00

## 🔧 Интеграция с Serverless функцией

После загрузки моделей, настройте endpoint:

1. **Создайте Serverless endpoint** в RunPod Console
2. **Примонтируйте том**: `shrill_coral_herring` → `/runpod-volume`
3. **Используйте Docker образ**: `vastai-video-gen-serverless:latest`
4. **Модели будут доступны** по путям:
   - `/runpod-volume/models/dreamshaper-xl-lightning/`
   - `/runpod-volume/models/CogVideoX-5b-I2V/`

### Код для проверки в handler:
```python
import os

# Проверка моделей
dreamshaper_path = "/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors"
cogvideox_path = "/runpod-volume/models/CogVideoX-5b-I2V/"

if os.path.exists(dreamshaper_path):
    print(f"✅ DreamShaper: {os.path.getsize(dreamshaper_path) / 1024**3:.1f}GB")
if os.path.exists(cogvideox_path):
    print(f"✅ CogVideoX: directory exists")
```

## 🛠️ Устранение неполадок

### Если том не найден:
```bash
# Проверить все тома
curl -s -X POST https://api.runpod.io/graphql \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d '{"query": "query { myself { networkVolumes { id name size } } }"}' \
  | jq '.data.myself.networkVolumes[]'
```

### Если загрузка медленная:
- Используйте `max_workers: 4` для параллельной загрузки
- Проверьте скорость сети
- Загружайте CogVideoX в фоновом режиме

### Если ошибки HuggingFace:
- Проверьте HF токен
- Убедитесь, что модель публичная или у вас есть доступ

## 📞 Поддержка

### Полезные ссылки:
- [RunPod API Documentation](https://docs.runpod.io/api/)
- [HuggingFace Hub](https://huggingface.co/docs/hub/)
- [RunPod Storage Guide](https://docs.runpod.io/serverless/storage/)

### При проблемах:
1. Проверьте баланс RunPod (> $1)
2. Убедитесь, что API ключ действителен
3. Проверьте интернет-соединение в pod
4. Увеличьте timeout для больших загрузок

## 🎉 Следующие шаги

После успешной загрузки моделей:

1. **Создайте Serverless endpoint** с примонтированным томом
2. **Протестируйте генерацию** с простым промптом
3. **Настройте автоматическую обработку** запросов
4. **Оптимизируйте производительность** при необходимости

## 📁 Файлы проекта

### Основные скрипты:
- `upload_models_api.sh` - автоматическая загрузка
- `check_volume.sh` - проверка тома
- `upload_models_simple.py` - инструкции

### Документация:
- `MODEL_UPLOAD_INSTRUCTIONS.md` - полное руководство
- `RUNPOD_DEPLOYMENT_GUIDE.md` - развертывание на RunPod
- `README_VASTAI_PIPELINE.md` - пайплайн на Vast AI

### Код:
- `src/entrypoints/runpod_handler.py` - обработчик для RunPod
- `docker/Dockerfile.serverless` - легковесный образ
- `run_vastai_pipeline.py` - пайплайн на Vast AI

---

## ✅ Готовность к продакшену

| Компонент | Статус | Примечания |
|-----------|--------|------------|
| Скрипты загрузки | ✅ Готово | Автоматическая и ручная версии |
| Документация | ✅ Готово | Полные инструкции |
| API интеграция | ✅ Готово | GraphQL + SSH |
| Модели | ⏳ Требует загрузки | ~24.5GB данных |
| Serverless endpoint | ⏳ Требует создания | После загрузки моделей |
| Тестирование | ⏳ Требует выполнения | После развертывания |

**Следующий шаг:** Запустить `./upload_models_api.sh` для загрузки моделей на том `shrill_coral_herring`.