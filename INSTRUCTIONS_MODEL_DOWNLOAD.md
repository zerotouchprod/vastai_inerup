# 📥 Инструкция по загрузке моделей на Network Volume

## 🎯 **Цель:**
Загрузить модели DreamShaper XL Lightning и CogVideoX-5b на Network Volume (`shrill_coral_herring`), чтобы они были доступны для всех RunPod pods.

## 📋 **Предварительные требования:**
1. **RunPod аккаунт** с API ключом
2. **Network Volume** `shrill_coral_herring` (ID: `gwmcixcs3e`) - 100GB
3. **Доступ к Web Terminal** любого RunPod pod

## 🚀 **Шаг 1: Подготовка временного pod**

### **Вариант A: Использовать существующий pod**
Если у вас уже есть запущенный pod (например, `video-gen-correct`):
1. Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
2. Найдите ваш pod
3. Нажмите "Connect" → "Launch Web Terminal"

### **Вариант B: Создать новый pod для загрузки**
```bash
# Используйте runpodctl или Web Console
runpodctl create pod \
  --name "model-downloader" \
  --imageName "pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime" \
  --gpuType "NVIDIA GeForce RTX 4090" \
  --gpuCount 1 \
  --networkVolumeId "gwmcixcs3e" \
  --volumePath "/workspace" \
  --ports "22/tcp" \
  --containerDiskSize 20 \
  --volumeSize 100 \
  --secureCloud
```

## 🚀 **Шаг 2: Установка зависимостей**

В Web Terminal выполните:

```bash
# 1. Обновить систему
apt-get update

# 2. Установить Python и git
apt-get install -y python3-pip git

# 3. Установить huggingface_hub
pip3 install huggingface_hub

# 4. Проверить подключение Network Volume
ls -la /workspace/
df -h /workspace
```

## 🚀 **Шаг 3: Копирование скрипта**

### **Вариант A: Клонировать репозиторий**
```bash
cd /workspace
git clone https://github.com/zerotouchprod/vastai_inerup.git
cd vastai_inerup
```

### **Вариант B: Создать скрипт вручную**
```bash
cd /workspace
mkdir -p scripts
# Создайте файл prepare_runpod_volume.py с содержимым из проекта
```

## 🚀 **Шаг 4: Запуск загрузки моделей**

```bash
# Перейти в директорию со скриптом
cd /workspace/vastai_inerup

# Запустить скрипт загрузки
python3 scripts/prepare_runpod_volume.py
```

### **Что произойдет:**
1. ✅ **Проверка Network Volume** - скрипт найдет `/workspace`
2. ✅ **Проверка свободного места** - нужно ~20GB
3. 📥 **Загрузка DreamShaper XL Lightning** (~2GB, 5-10 минут)
4. 📥 **Загрузка CogVideoX-5b-I2V** (~15GB, 30-60 минут)
5. ✅ **Верификация загрузки** - проверка файлов и размеров

## 🚀 **Шаг 5: Проверка загрузки**

```bash
# Проверить загруженные модели
ls -la /workspace/models/
du -sh /workspace/models/*

# Ожидаемый результат:
# /workspace/models/dreamshaper-xl-lightning/ - ~2GB
# /workspace/models/CogVideoX-5b-I2V/ - ~15GB

# Проверить конкретные файлы
ls -la /workspace/models/dreamshaper-xl-lightning/
ls -la /workspace/models/CogVideoX-5b-I2V/ | head -20
```

## 🚀 **Шаг 6: Резервное копирование (опционально)**

```bash
# Создать backup моделей
tar -czf /workspace/backup_models.tar.gz /workspace/models/

# Проверить размер backup
du -sh /workspace/backup_models.tar.gz
```

## 🚀 **Шаг 7: Очистка**

### **Если создавали временный pod:**
1. Вернитесь в RunPod Console
2. Найдите pod `model-downloader`
3. Нажмите "Stop" или "Remove"
4. **Не забудьте удалить pod**, чтобы не платить за него!

### **Если использовали существующий pod:**
Просто закройте Web Terminal.

## ⏱️ **Ожидаемое время загрузки:**

| Модель | Размер | Время загрузки |
|--------|--------|----------------|
| DreamShaper XL Lightning | ~2GB | 5-10 минут |
| CogVideoX-5b-I2V | ~15GB | 30-60 минут |
| **Итого** | **~17GB** | **35-70 минут** |

## 🔧 **Устранение проблем:**

### **1. Network Volume не найден:**
```bash
# Проверить mount points
mount | grep workspace
mount | grep volume

# Проверить доступные диски
df -h
ls -la /workspace /runpod-volume /volume
```

### **2. Недостаточно места:**
```bash
# Проверить свободное место
df -h /workspace

# Очистить кэш (если нужно)
rm -rf /workspace/.cache/*
```

### **3. Ошибка загрузки HuggingFace:**
```bash
# Проверить интернет соединение
curl -I https://huggingface.co

# Использовать токен (если нужно)
export HF_TOKEN="your_token_here"
```

### **4. Медленная загрузка:**
```bash
# Запустить в фоне и мониторить
python3 scripts/prepare_runpod_volume.py > /tmp/download.log 2>&1 &
tail -f /tmp/download.log
```

## 🎉 **Готово!**

После успешной загрузки:
- ✅ **Модели сохранены** на Network Volume
- ✅ **Доступны всем pods** с этим volume
- ✅ **Готово к использованию** в serverless handler

## 📁 **Структура после загрузки:**

```
/workspace/
├── models/
│   ├── dreamshaper-xl-lightning/
│   │   └── dreamshaperXL_lightningDPMSDE.safetensors
│   └── CogVideoX-5b-I2V/
│       ├── config.json
│       ├── model.safetensors
│       └── ... (другие файлы)
└── backup_models.tar.gz (опционально)
```

## 🔗 **Полезные ссылки:**
- [RunPod Console](https://www.runpod.io/console/pods)
- [Network Volume Documentation](https://docs.runpod.io/serverless/network-volumes)
- [HuggingFace Hub](https://huggingface.co/models)

---

**Примечание:** Загрузка моделей выполняется **только один раз**. После этого они будут доступны для всех pods, подключенных к этому Network Volume. 🚀