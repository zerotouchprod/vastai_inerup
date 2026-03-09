# Загрузка моделей на RunPod сетевой том `shrill_coral_herring`

## 📋 Обзор

Это руководство описывает загрузку весов моделей на сетевой том RunPod `shrill_coral_herring` для использования в пайплайне генерации видео.

## 🎯 Что нужно загрузить

| Модель | Репозиторий | Размер | Назначение |
|--------|-------------|--------|------------|
| **DreamShaper XL Lightning** | `ByteDance/SDXL-Lightning` | ~6.5GB | Text-to-Image (T2I) |
| **CogVideoX-5b** | `THUDM/CogVideoX-5b` | ~18GB | Image-to-Video (I2V) |
| **Итого** | - | **~24.5GB** | Полный пайплайн |

## 🚀 Быстрый способ (автоматический)

### Требования:
- Установленный `curl` и `jq`
- API ключ RunPod: `your_runpod_api_key_here`
- Опционально: HuggingFace токен (для частных моделей)

### Запуск:
```bash
# Сделайте скрипт исполняемым
chmod +x upload_models_api.sh

# Запустите (с HF токеном если нужно)
HF_TOKEN=your_hf_token ./upload_models_api.sh

# Или без HF токена
./upload_models_api.sh
```

### Что делает скрипт:
1. Находит том `shrill_coral_herring`
2. Создает временный pod с RTX 4090
3. Устанавливает необходимые инструменты
4. Загружает обе модели
5. Уничтожает временный pod
6. Выводит отчет

## 🔧 Ручной способ (пошагово)

### Шаг 1: Найти ID тома
```bash
API_KEY="your_runpod_api_key_here"

curl -s -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"query": "query { myself { networkVolumes { id name size } } }"}' \
  | jq -r '.data.myself.networkVolumes[] | select(.name == "shrill_coral_herring") | .id'
```

### Шаг 2: Создать временный pod
```bash
VOLUME_ID="your_volume_id"  # Из шага 1

curl -s -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "query": "mutation($input: PodFindAndDeployOnDemandInput!) { podFindAndDeployOnDemand(input: $input) { id imageName env machineId } }",
    "variables": {
      "input": {
        "cloudType": "SECURE",
        "gpuCount": 1,
        "volumeInGb": 100,
        "containerDiskSizeGb": 50,
        "minVcpuCount": 2,
        "minMemoryInGb": 15,
        "gpuTypeId": "NVIDIA GeForce RTX 4090",
        "name": "model-downloader",
        "imageName": "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime",
        "dockerArgs": "",
        "ports": "22/tcp",
        "volumeMountPath": "/runpod-volume",
        "env": [
          {"key": "HF_HOME", "value": "/root/.cache/huggingface"}
        ]
      }
    }
  }' | jq -r '.data.podFindAndDeployOnDemand.id'
```

### Шаг 3: Получить SSH доступ
```bash
POD_ID="your_pod_id"  # Из шага 2

# Получить SSH детали
curl -s -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d "{
    \"query\": \"query(\$podId: String!) { pod(input: {podId: \$podId}) { id runtime { ports { ip isIpPublic privatePort publicPort } } } }\",
    \"variables\": {\"podId\": \"$POD_ID\"}
  }" | jq -r '.data.pod.runtime.ports[] | select(.privatePort==22) | \"ssh -p \(.publicPort) root@\(.ip)\"'
```

### Шаг 4: Подключиться и загрузить модели
```bash
# Подключиться (используйте IP и порт из шага 3)
ssh -p <PORT> root@<IP>

# Внутри контейнера:
# 1. Установить инструменты
apt-get update && apt-get install -y git-lfs wget curl python3-pip
pip3 install huggingface-hub==0.24.0
git lfs install

# 2. Создать директории
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# 3. Загрузить DreamShaper
cd /runpod-volume/models/dreamshaper-xl-lightning
python3 -c "
from huggingface_hub import hf_hub_download
import os
hf_hub_download(
    repo_id='ByteDance/SDXL-Lightning',
    filename='sdxl_lightning_4step_unet.safetensors',
    local_dir='.',
    local_dir_use_symlinks=False
)
"

# 4. Загрузить CogVideoX (в фоне, т.к. долго)
cd /runpod-volume/models/CogVideoX-5b-I2V
python3 -c "
from huggingface_hub import snapshot_download
import os
snapshot_download(
    repo_id='THUDM/CogVideoX-5b',
    local_dir='.',
    local_dir_use_symlinks=False,
    ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
    max_workers=4
)
" > /tmp/cogvideox.log 2>&1 &

# 5. Проверить прогресс
tail -f /tmp/cogvideox.log
# Или
ps aux | grep python | grep huggingface
du -sh /runpod-volume/models/*
```

### Шаг 5: Проверить и завершить
```bash
# Проверить загрузку
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/
ls -lh /runpod-volume/models/CogVideoX-5b-I2V/ | head -10
du -sh /runpod-volume/models/*

# Выйти из SSH
exit

# Уничтожить pod
curl -s -X POST https://api.runpod.io/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d "{
    \"query\": \"mutation(\$input: PodStopInput!) { podStop(input: \$input) { id } }\",
    \"variables\": {\"input\": {\"podId\": \"$POD_ID\"}}
  }"
```

## 📁 Ожидаемая структура файлов

```
/runpod-volume/models/
├── dreamshaper-xl-lightning/
│   └── sdxl_lightning_4step_unet.safetensors  (6.5GB)
└── CogVideoX-5b-I2V/
    ├── diffusion_pytorch_model.safetensors     (18GB)
    ├── config.json
    ├── model_index.json
    ├── scheduler/
    │   └── scheduler_config.json
    ├── text_encoder/
    │   ├── config.json
    │   └── model.safetensors
    ├── tokenizer/
    │   └── tokenizer_config.json
    ├── unet/
    │   ├── config.json
    │   └── diffusion_pytorch_model.safetensors
    └── vae/
        ├── config.json
        └── diffusion_pytorch_model.safetensors
```

## ⏱️ Время загрузки

| Действие | Время |
|----------|-------|
| Создание pod | 2-5 минут |
| Установка инструментов | 2-3 минуты |
| DreamShaper (6.5GB) | 5-15 минут |
| CogVideoX (18GB) | 30-60 минут |
| **Итого** | **40-85 минут** |

## 💰 Стоимость

| Компонент | Стоимость |
|-----------|-----------|
| RTX 4090 pod (1 час) | $0.70-$1.20 |
| Сетевой том (100GB) | $50/месяц |
| **Итого за загрузку** | **~$1.00** |

## 🛠️ Устранение неполадок

### Проблема: Том не найден
```bash
# Проверить все тома
curl -s -X POST https://api.runpod.io/graphql \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"query": "query { myself { networkVolumes { id name size } } }"}' \
  | jq '.data.myself.networkVolumes[] | "\(.name) (\(.id)) - \(.size)GB"'
```

### Проблема: Недостаточно места
- Убедитесь, что том имеет минимум 50GB свободного места
- CogVideoX требует ~18GB, DreamShaper ~6.5GB

### Проблема: Медленная загрузка
- Используйте `max_workers: 4` для параллельной загрузки
- Проверьте скорость сети: `curl -s https://speedtest.runpod.io/`
- Используйте фоновую загрузку для CogVideoX

### Проблема: Ошибки HuggingFace
```bash
# Проверить токен
echo $HF_TOKEN

# Тест загрузки
python3 -c "from huggingface_hub import whoami; print(whoami())"
```

## ✅ Проверка успешной загрузки

### Команды проверки:
```bash
# Размер файлов
du -sh /runpod-volume/models/*

# Конкретные файлы
find /runpod-volume/models -name "*.safetensors" -type f | xargs ls -lh

# Проверка целостности
file /runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors
file /runpod-volume/models/CogVideoX-5b-I2V/diffusion_pytorch_model.safetensors
```

### Ожидаемый вывод:
```
24G     /runpod-volume/models
6.5G    /runpod-volume/models/dreamshaper-xl-lightning
18G     /runpod-volume/models/CogVideoX-5b-I2V
```

## 🔄 Использование в Serverless функции

После загрузки моделей, настройте Serverless endpoint:

1. **Создайте endpoint** в RunPod Console
2. **Примонтируйте том**: `shrill_coral_herring` → `/runpod-volume`
3. **Используйте Docker образ**: `vastai-video-gen-serverless:latest`
4. **Модели будут доступны** по пути: `/runpod-volume/models/`

### Код для проверки в handler:
```python
import os

model_paths = {
    "dreamshaper": "/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors",
    "cogvideox": "/runpod-volume/models/CogVideoX-5b-I2V/"
}

for name, path in model_paths.items():
    if os.path.exists(path):
        print(f"✅ {name}: Found at {path}")
        size = os.path.getsize(path) if os.path.isfile(path) else "directory"
        print(f"   Size: {size}")
    else:
        print(f"❌ {name}: Not found at {path}")
```

## 📞 Поддержка

### Полезные ссылки:
- [RunPod API Documentation](https://docs.runpod.io/api/)
- [HuggingFace Hub Python Library](https://huggingface.co/docs/huggingface_hub/index)
- [RunPod Storage Guide](https://docs.runpod.io/serverless/storage/)

### При проблемах:
1. Проверьте баланс RunPod (> $1)
2. Убедитесь, что API ключ действителен
3. Проверьте интернет-соединение в pod
4. Увеличьте timeout для больших загрузок

---

## 🎉 Готово!

После успешной загрузки моделей вы можете:
1. Создать Serverless endpoint с примонтированным томом
2. Протестировать генерацию видео
3. Настроить автоматическую обработку запросов

**Следующие шаги:** Создание Serverless endpoint и тестирование пайплайна.