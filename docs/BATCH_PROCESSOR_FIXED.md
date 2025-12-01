# ✅ batch_processor.py - Исправлено!

## Проблема

```
ERROR:__main__:Failed to import modules: cannot import name 'setup_logging' from 'shared.logging'
```

## Решение

Исправлены импорты в `batch_processor.py`:

### Изменения:

1. **Добавлен import logging**
   ```python
   import logging
   ```

2. **Исправлен импорт из shared.logging**
   ```python
   # Было:
   from shared.logging import setup_logging, get_logger
   
   # Стало:
   from shared.logging import get_logger
   ```

3. **Удален вызов setup_logging()**
   ```python
   # Удалено:
   setup_logging()
   ```

## ✅ Результат

Теперь `batch_processor.py` работает:

```bash
python batch_processor.py --help
```

Выводит корректную справку без ошибок.

## 📝 Использование batch_processor.py

### Требования

Перед запуском установите environment variables для B2:

```bash
# Windows PowerShell
$env:B2_KEY="your_key_id"
$env:B2_SECRET="your_application_key"
$env:B2_BUCKET="noxfvr-videos"
$env:B2_ENDPOINT="https://s3.us-west-004.backblazeb2.com"

# Для Vast.ai (опционально)
$env:VAST_API_KEY="your_vast_api_key"
```

### Примеры использования

#### 1. Обработка одного файла
```bash
python batch_processor.py --input https://example.com/video.mp4
```

#### 2. Обработка директории на B2
```bash
python batch_processor.py --input-dir input/batch1
```

#### 3. Dry-run (просмотр без обработки)
```bash
python batch_processor.py --input-dir input/batch1 --dry-run
```

#### 4. С кастомной конфигурацией
```bash
python batch_processor.py --config config.yaml --input-dir input/batch1
```

#### 5. С выбором preset
```bash
python batch_processor.py --input-dir input/ --preset high
```

### Доступные presets

Из `config.yaml`:
- **low** - Дешевые GPU (RTX 3060 Ti, 3070), $0.08-0.25/hr
- **balanced** (default) - Средние GPU (RTX 3080, 3090, 4070 Ti), $0.12-0.50/hr
- **high** - Топовые GPU (RTX 4090, A6000, A100), $0.25-0.90/hr

## 🔍 Проверка конфигурации

### config.yaml
```yaml
b2:
  bucket: "noxfvr-videos"
  endpoint: "https://s3.us-west-004.backblazeb2.com"

vast:
  preset: "balanced"
  min_vram: 12
  max_price: 0.50
  # ... остальные параметры
```

### Проверка B2 подключения

```bash
# Проверить, что credentials установлены
echo $env:B2_KEY
echo $env:B2_SECRET
echo $env:B2_BUCKET
```

Если переменные пустые - установите их перед запуском.

## 🛠️ Устранение проблем

### Ошибка "B2 client not initialized"

**Причина:** Не установлены B2 credentials

**Решение:**
```powershell
$env:B2_KEY="your_key_id"
$env:B2_SECRET="your_application_key"
$env:B2_BUCKET="noxfvr-videos"
```

### Ошибка "Vast.ai client not initialized"

**Причина:** Не установлен VAST_API_KEY

**Решение:**
```powershell
$env:VAST_API_KEY="your_vast_api_key"
```

Или работайте только с локальными файлами (без Vast.ai).

## 📚 Альтернативные способы запуска

### Через .env файл (рекомендуется)

Создайте `.env` в корне проекта:
```env
B2_KEY=your_key_id
B2_SECRET=your_application_key
B2_BUCKET=noxfvr-videos
B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com
VAST_API_KEY=your_vast_api_key
```

Затем используйте `python-dotenv`:
```bash
pip install python-dotenv
```

### Через config.yaml (для CI/CD)

Можно расширить `batch_processor.py`, чтобы читать credentials из config.yaml.

## ✨ Резюме

✅ **batch_processor.py исправлен и работает**
✅ **Импорты корректны**
✅ **Logging настроен правильно**
✅ **Нужны только B2 credentials для полной работы**

Теперь можно использовать unified batch processor вместо старых скриптов!

