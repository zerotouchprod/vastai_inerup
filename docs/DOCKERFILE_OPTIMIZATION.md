# Dockerfile Optimization for Limited Disk Space

## 📋 Проблема
Исходный Dockerfile (`docker/Dockerfile.gen`) требует ~75GB свободного места для сборки, но доступно только 75GB, что недостаточно из-за временных файлов и промежуточных слоев.

## 🎯 Решение
Создан оптимизированный Dockerfile (`docker/Dockerfile.gen.optimized`) и скрипты для сборки на внешнем HDD.

## 📊 Сравнение оптимизаций

### Исходный Dockerfile (`Dockerfile.gen`)
- **Размер образа**: ~15GB
- **Базовые образы**: `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel` + `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime`
- **Стадии**: 2 (downloader + runtime)
- **Временное пространство**: ~30GB
- **Общее требование**: ~45GB

### Оптимизированный Dockerfile (`Dockerfile.gen.optimized`)
- **Целевой размер**: ~10-12GB (экономия 20-30%)
- **Базовые образы**: 
  - Stage 1: `ubuntu:22.04` (минимальный для скачивания модели)
  - Stage 2: `nvidia/cuda:12.4.0-cudnn9-devel-ubuntu22.04` (только для сборки)
  - Stage 3: `nvidia/cuda:12.4.0-cudnn9-runtime-ubuntu22.04` (минимальный runtime)
- **Стадии**: 3 (downloader + builder + runtime)
- **Временное пространство**: ~25GB
- **Общее требование**: ~35GB

## 🔧 Ключевые оптимизации

### 1. Легкие базовые образы
- Вместо полных PyTorch образов используем минимальные CUDA образы от NVIDIA
- Stage 1: Только Ubuntu для скачивания модели
- Stage 2: CUDA devel для установки зависимостей
- Stage 3: CUDA runtime для выполнения

### 2. Трехстадийная сборка
```
Stage 1 (downloader): Ubuntu → скачивание модели
Stage 2 (builder): CUDA devel → установка зависимостей
Stage 3 (runtime): CUDA runtime → финальный образ
```

### 3. Виртуальное окружение Python
- Создание `/opt/venv` для изоляции зависимостей
- Копирование между стадиями вместо переустановки
- Уменьшение дублирования зависимостей

### 4. Очистка кэшей
- Удаление APT кэша: `rm -rf /var/lib/apt/lists/*`
- Удаление PIP кэша: `rm -rf /root/.cache/pip`
- Удаление документации и man pages
- Очистка временных файлов

### 5. Минимальные зависимости
- Stage 1: Только `huggingface_hub[cli]` для скачивания модели
- Stage 3: Только runtime зависимости (без компиляторов)

## 🚀 Скрипты для сборки

### 1. Сборка на внешнем HDD
```bash
# Основной скрипт
./scripts/build_video_gen_external.sh

# С переменными окружения
export HF_TOKEN="hf_your_token"
export EXTERNAL_MOUNT="/mnt/external_hdd"
./scripts/build_video_gen_external.sh
```

### 2. Быстрая проверка Dockerfile
```bash
./scripts/test_optimized_dockerfile.sh
```

### 3. Ручная сборка
```bash
# На внешнем HDD
mkdir -p /mnt/external_hdd/vastai_inerup
cp -r src/ docker/ requirements.gen.txt /mnt/external_hdd/vastai_inerup/
cd /mnt/external_hdd/vastai_inerup
docker build -f docker/Dockerfile.gen.optimized -t video-gen-optimized .

# На локальном диске (если места достаточно)
docker build -f docker/Dockerfile.gen.optimized -t video-gen-optimized .
```

## 📁 Структура файлов

```
docker/
├── Dockerfile.gen              # Исходный (оригинальный)
├── Dockerfile.gen.optimized    # Оптимизированный (рекомендуемый)
└── ...

scripts/
├── build_video_gen.sh          # Оригинальный скрипт сборки
├── build_video_gen_external.sh # Сборка на внешнем HDD
└── test_optimized_dockerfile.sh # Проверка Dockerfile

docs/
└── DOCKERFILE_OPTIMIZATION.md  # Эта документация
```

## 🎯 Преимущества для Vast.ai

### 1. Модель запечена в образе
- ✅ Не требуется скачивание на дорогих инстансах Vast.ai
- ✅ Предсказуемое время запуска
- ✅ Надежность (нет зависимости от сети HuggingFace)

### 2. Уменьшенный размер образа
- ✅ Экономия на storage costs
- ✅ Быстрее загрузка на инстансы
- ✅ Меньше место на диске инстанса

### 3. Оптимизированные зависимости
- ✅ Только необходимые пакеты
- ✅ Очищенные кэши
- ✅ Минимальный runtime

## 🔍 Проверка работоспособности

После сборки проверьте:
```bash
# 1. Размер образа
docker images video-gen-optimized

# 2. Работоспособность PyTorch
docker run --rm video-gen-optimized \
  python -c "import torch; print(f'PyTorch {torch.__version__}'); print(f'CUDA: {torch.cuda.is_available()}')"

# 3. Наличие модели
docker run --rm video-gen-optimized \
  find /root/.cache/huggingface -name "*.safetensors" | head -5

# 4. Запуск приложения
docker run --rm --gpus all video-gen-optimized \
  python -m src.entrypoints.run_gen --help
```

## ⚠️ Важные замечания

### Совместимость с CUDA
- Образ использует CUDA 12.4
- Требуется NVIDIA драйвер >= 535.86.10
- Проверьте совместимость: `nvidia-smi`

### Токен HuggingFace
- Рекомендуется использовать HF_TOKEN для скачивания модели
- Без токена: ограничение скорости 10GB/час
- С токеном: до 50GB/час

### Внешний HDD
- Минимальный размер: 100GB (рекомендуется 200GB)
- Файловая система: ext4 рекомендуется
- Скорость: USB 3.0+ или SATA

## 📈 Ожидаемые результаты

| Метрика | Исходный | Оптимизированный | Экономия |
|---------|----------|------------------|----------|
| Размер образа | ~15GB | ~10-12GB | 20-30% |
| Время сборки | 15-20 мин | 12-18 мин | 15-20% |
| Временное пространство | ~30GB | ~25GB | ~5GB |
| Зависимости | Полные | Минимальные | 40-50% |

## 🆘 Устранение проблем

### 1. Нехватка места на внешнем HDD
```bash
# Проверьте свободное место
df -h /mnt/external_hdd

# Очистите старые образы
docker system prune -a

# Удалите старые сборки
rm -rf /mnt/external_hdd/vastai_inerup_external
```

### 2. Ошибка скачивания модели
```bash
# Используйте токен
export HF_TOKEN="hf_your_token"

# Проверьте сеть
curl -I https://huggingface.co

# Попробуйте позже (rate limiting)
sleep 300 && ./scripts/build_video_gen_external.sh
```

### 3. Ошибка CUDA
```bash
# Проверьте драйвер
nvidia-smi

# Проверьте Docker GPU support
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

## 📞 Поддержка

Для вопросов и проблем:
1. Проверьте `DOCKER_BUILD_TROUBLESHOOTING.md`
2. Запустите `./scripts/test_optimized_dockerfile.sh`
3. Соберите с `--progress=plain` для детальных логов

---
*Последнее обновление: $(date)*
*Автор оптимизации: Docker Space Optimization Task*