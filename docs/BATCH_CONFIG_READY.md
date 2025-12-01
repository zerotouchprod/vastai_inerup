# ✅ batch_processor.py теперь работает с config.yaml!

## Что изменилось

### Раньше (требовались параметры):
```bash
python batch_processor.py --input-dir input/queue
# error: Either --input or --input-dir required
```

### Теперь (читает из config.yaml):
```bash
python batch_processor.py
# ✅ Читает input_dir из config.yaml!
```

## 🔧 Изменения

### 1. Добавлена секция `batch` в config.yaml

```yaml
# Batch processing settings
batch:
  # Input directory in B2 bucket (relative to bucket root)
  input_dir: "input/queue"
  
  # Preset to use for batch processing
  preset: "balanced"
  
  # Skip files that already have output
  skip_existing: true
  
  # Maximum number of files to process in one batch
  max_files: 100
  
  # Dry run mode (don't actually submit to Vast.ai)
  dry_run: false
```

### 2. batch_processor.py теперь читает defaults из конфига

- ✅ Все CLI параметры опциональны
- ✅ Значения берутся из `config.yaml` по умолчанию
- ✅ CLI параметры переопределяют конфиг (если указаны)

## 📝 Использование

### Вариант 1: Только конфиг (новое!)

```bash
# Просто запустить - возьмёт всё из config.yaml
python batch_processor.py

# Сухой прогон (проверить что будет обработано)
python batch_processor.py --dry-run
```

### Вариант 2: Конфиг + переопределение

```bash
# Использовать другую директорию
python batch_processor.py --input-dir input/urgent

# Использовать другой preset
python batch_processor.py --preset high

# Всё вместе
python batch_processor.py --input-dir input/urgent --preset high --dry-run
```

### Вариант 3: Одиночный файл

```bash
# Обработать один файл (игнорирует batch секцию в конфиге)
python batch_processor.py --input https://example.com/video.mp4
```

## ⚙️ Настройка config.yaml

Отредактируйте секцию `batch`:

```yaml
batch:
  input_dir: "input/queue"     # ← Ваша директория в B2
  preset: "balanced"            # ← low / balanced / high
  skip_existing: true           # ← Пропускать обработанные
  max_files: 100                # ← Лимит файлов за раз
  dry_run: false                # ← true = только показать, не запускать
```

## 🔑 Требуются credentials

Для работы с B2 и Vast.ai установите переменные окружения:

```powershell
# B2 Storage
$env:B2_KEY="your_key_id"
$env:B2_SECRET="your_application_key"
$env:B2_BUCKET="noxfvr-videos"
$env:B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com"

# Vast.ai
$env:VAST_API_KEY="your_vast_api_key"
```

Или создайте `.env` файл:

```env
B2_KEY=your_key_id
B2_SECRET=your_application_key
B2_BUCKET=noxfvr-videos
B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com
VAST_API_KEY=your_vast_api_key
```

## 📊 Примеры работы

### Проверить конфигурацию (dry-run)
```bash
python batch_processor.py --dry-run
```

Вывод:
```
📁 Processing batch from: input/queue
⚙️  Preset: balanced
🔍 Dry run: True
⏭️  Skip existing: True

📄 Would process:
  - input/queue/video1.mp4
  - input/queue/video2.mp4
  - input/queue/video3.mp4
```

### Реальная обработка
```bash
python batch_processor.py
```

Вывод:
```
📁 Processing batch from: input/queue
⚙️  Preset: balanced
🔍 Dry run: False
⏭️  Skip existing: True

🚀 Submitting to Vast.ai...
✅ Batch processing complete: 3 files submitted
```

### Срочная обработка (другая директория + высокий preset)
```bash
python batch_processor.py --input-dir input/urgent --preset high
```

## 🎯 Преимущества

✅ **Быстрый запуск**: просто `python batch_processor.py`  
✅ **Централизованная конфигурация**: всё в `config.yaml`  
✅ **Гибкость**: можно переопределить любой параметр через CLI  
✅ **Версионирование**: конфиг в Git, легко отслеживать изменения  
✅ **CI/CD ready**: легко автоматизировать  

## 🔍 Справка

```bash
python batch_processor.py --help
```

Покажет:
```
Unified Batch Processor for Vast.ai - reads defaults from config.yaml

options:
  --config CONFIG       Config file (default: config.yaml)
  --input INPUT         Single input file URL (overrides config)
  --input-dir INPUT_DIR Input directory in B2 (overrides config)
  --output OUTPUT       Output file name (for single file)
  --preset PRESET       Preset name (overrides config)
  --dry-run             Show what would be processed (overrides config)
  --skip-existing       Skip files with existing output (overrides config)
```

## ✨ Итог

Теперь `batch_processor.py` работает **из коробки** с конфигом!

```bash
# Настроил config.yaml один раз
# Теперь просто:
python batch_processor.py
```

**Готово!** 🎉

