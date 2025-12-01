# ✅ Remote Config Support - Готово!

## 🎯 Что реализовано

Добавлена поддержка **динамической загрузки конфигурации** из удалённого URL при каждом запуске.

### Что это даёт

✅ Централизованное управление конфигурацией  
✅ Быстрые изменения без пересборки Docker  
✅ Разные конфиги для разных сред  
✅ A/B тестирование параметров  
✅ Удобная отладка и настройка  

---

## 📋 Как работает

### 1. В config.yaml указан URL

```yaml
config_url: "https://gist.githubusercontent.com/.../config.json"
```

### 2. При запуске скачивается remote config

```json
{
  "video": {
    "input_dir": "input/c1",
    "mode": "both",
    "scale": 2,
    "target_fps": 60,
    "overwrite": true
  }
}
```

### 3. Параметры мержатся

**Базовый config.yaml** + **Remote config.json** = **Merged config**

```yaml
# Результат merge:
video:
  input_dir: "input/c1"      # ← из remote
  mode: "both"               # ← из remote
  scale: 2                   # ← из remote
  target_fps: 60             # ← из remote
  overwrite: true            # ← из remote

# Остальные параметры из config.yaml сохраняются:
b2:
  bucket: "noxfvr-videos"
vast:
  preset: "balanced"
# ...
```

---

## 🔧 Реализация

### 1. Модуль `shared/remote_config.py`

Создан централизованный модуль для работы с remote config:

```python
from shared.remote_config import load_config_with_remote

# Загрузить config.yaml + merge с remote config
config = load_config_with_remote(Path('config.yaml'))
```

**Функции:**
- `deep_merge()` - глубокое слияние словарей
- `download_remote_config()` - скачивание конфига по URL
- `load_config_with_remote()` - загрузка и merge
- `save_merged_config()` - сохранение результата

### 2. Обновлён `entrypoint.sh`

При запуске контейнера:
1. Обновляется код из Git
2. **Скачивается remote config** (если config_url задан)
3. **Мержится с config.yaml**
4. Запускается обработка

```bash
[entrypoint] Found remote config_url: https://...
[entrypoint] Remote config downloaded — merging with config.yaml
[entrypoint] ✓ Remote config merged successfully
[entrypoint]   video params: {'mode': 'both', 'scale': 2, ...}
```

### 3. Обновлён `batch_processor.py`

Использует `load_config_with_remote()` при загрузке конфига:

```python
def _load_config(self) -> Dict[str, Any]:
    """Load config + merge remote if config_url is set."""
    return load_config_with_remote(Path(self.config_path), logger_instance=logger)
```

**Вывод при запуске:**
```
📥 Downloading remote config: https://...
✓ Remote config parsed as JSON
✓ Remote config merged: ['video']
  video params: {'input_dir': 'input/c1', 'mode': 'both', ...}
```

---

## 📊 Примеры использования

### Сценарий 1: Базовая конфигурация

**config.yaml (в Git):**
```yaml
config_url: "https://gist.githubusercontent.com/.../config.json"
b2:
  bucket: "noxfvr-videos"
vast:
  preset: "balanced"
```

**config.json (remote, обновляется часто):**
```json
{
  "video": {
    "input_dir": "input/urgent",
    "mode": "upscale",
    "scale": 4
  }
}
```

**Результат:**
- Bucket, preset и прочее - из config.yaml (стабильно)
- input_dir, mode, scale - из remote (гибко)

### Сценарий 2: A/B тестирование

**Remote config для теста:**
```json
{
  "video": {
    "mode": "both",
    "scale": 2,
    "target_fps": 60
  },
  "batch": {
    "preset": "high"
  }
}
```

Изменил URL в remote - все контейнеры получат новые параметры при следующем запуске!

### Сценарий 3: Разные среды

**Production:**
```yaml
config_url: "https://gist.github.com/.../prod.json"
```

**Staging:**
```yaml
config_url: "https://gist.github.com/.../staging.json"
```

**Development:**
```yaml
# config_url не указан - используется локальный config.yaml
```

---

## 🚀 Использование

### 1. Создать remote config

**Где хостить:**
- GitHub Gist (рекомендуется)
- Google Drive (public link)
- Собственный сервер
- S3/B2 с public URL

**Формат:**
- JSON (рекомендуется)
- YAML (тоже поддерживается)

**Пример (GitHub Gist):**

1. Создать gist: https://gist.github.com/
2. Файл: `config.json`
3. Содержимое:
```json
{
  "video": {
    "input_dir": "input/queue",
    "mode": "both",
    "scale": 2,
    "target_fps": 60,
    "overwrite": true
  },
  "batch": {
    "preset": "balanced",
    "skip_existing": true
  }
}
```
4. Сохранить как Public gist
5. Скопировать Raw URL

### 2. Добавить URL в config.yaml

```yaml
config_url: "https://gist.githubusercontent.com/user/id/raw/config.json"

# Остальная конфигурация
b2:
  bucket: "noxfvr-videos"
# ...
```

### 3. Запустить

```bash
# Локально
python batch_processor.py

# В контейнере (автоматически при entrypoint)
# config скачается и смержится
```

**Вывод:**
```
📥 Downloading remote config: https://gist...
✓ Remote config parsed as JSON
✓ Remote config merged: ['video', 'batch']
  video params: {'input_dir': 'input/queue', 'mode': 'both', ...}
  batch params: {'preset': 'balanced', ...}
```

---

## 🔍 Deep Merge логика

### Приоритет параметров

**Remote config > Local config**

```yaml
# Local config.yaml:
video:
  mode: "upscale"
  scale: 2
  fps: 24

# Remote config.json:
{
  "video": {
    "scale": 4,
    "target_fps": 60
  }
}

# Результат merge:
video:
  mode: "upscale"      # ← из local (сохранился)
  scale: 4             # ← из remote (перезаписался)
  fps: 24              # ← из local (сохранился)
  target_fps: 60       # ← из remote (добавился)
```

### Вложенные словари

Deep merge работает рекурсивно:

```python
base = {
    'video': {'mode': 'upscale', 'scale': 2},
    'batch': {'preset': 'low'}
}

remote = {
    'video': {'scale': 4},  # Только scale
    'new_key': 'value'
}

# Результат:
{
    'video': {
        'mode': 'upscale',  # Сохранилось из base
        'scale': 4          # Перезаписалось из remote
    },
    'batch': {
        'preset': 'low'     # Сохранилось из base
    },
    'new_key': 'value'      # Добавилось из remote
}
```

---

## ✅ Тестирование

Создано **15 unit тестов** для `shared/remote_config.py`:

```bash
pytest tests/unit/test_remote_config.py -v
```

**Покрытие:**
- ✅ Deep merge (4 теста)
- ✅ Download remote config (5 тестов)
- ✅ Load config with remote (4 теста)
- ✅ Save merged config (2 теста)

**Результат:**
```
15 passed in 0.41s ✅
```

---

## 📚 API Documentation

### `deep_merge(base, override)`

Глубокое слияние словарей.

**Args:**
- `base`: базовая конфигурация
- `override`: конфигурация для слияния (приоритет выше)

**Returns:** merged dict

### `download_remote_config(config_url, timeout=10, logger_instance=None)`

Скачать и распарсить remote config.

**Args:**
- `config_url`: URL конфига
- `timeout`: таймаут запроса (сек)
- `logger_instance`: опциональный logger

**Returns:** dict или None (если ошибка)

### `load_config_with_remote(config_path, logger_instance=None)`

Загрузить config.yaml и смержить с remote config (если config_url задан).

**Args:**
- `config_path`: Path к config.yaml
- `logger_instance`: опциональный logger

**Returns:** merged dict

**Raises:** FileNotFoundError если config.yaml не найден

### `save_merged_config(config, config_path, logger_instance=None)`

Сохранить merged config обратно в файл.

**Args:**
- `config`: конфигурация для сохранения
- `config_path`: Path для сохранения
- `logger_instance`: опциональный logger

**Returns:** bool (успех/неудача)

---

## 🎯 Преимущества

### 1. Гибкость
- Изменить параметры без пересборки Docker
- Разные конфиги для разных инстансов
- A/B тестирование

### 2. Централизация
- Один remote config для всех контейнеров
- Легко откатить изменения (изменить gist)
- Версионирование через Git/Gist history

### 3. Безопасность
- Секреты остаются в ENV variables
- Remote config только для бизнес-логики
- config.yaml в Git для базовых параметров

### 4. Удобство
- Быстрая отладка на production
- Смена input_dir без перезапуска
- Эксперименты с параметрами

---

## 🔐 Безопасность

### ✅ Что можно в remote config

- input_dir, output_dir
- mode, scale, target_fps
- preset, batch настройки
- Любые бизнес-параметры

### ❌ Что НЕ НУЖНО в remote config

- B2_KEY, B2_SECRET
- VAST_API_KEY
- bucket names (лучше в local config)
- endpoint URLs

**Секреты - только в ENV variables!**

---

## 📝 Checklist

Реализовано:

- ✅ Модуль `shared/remote_config.py`
- ✅ Deep merge логика
- ✅ Download remote config (JSON/YAML)
- ✅ Обновлён `entrypoint.sh`
- ✅ Обновлён `batch_processor.py`
- ✅ 15 unit тестов
- ✅ Документация
- ✅ Проверено в runtime

---

## 🚀 Быстрый старт

1. **Создать GitHub Gist:**
```json
{
  "video": {
    "input_dir": "input/urgent",
    "mode": "both",
    "scale": 2,
    "target_fps": 60
  }
}
```

2. **Добавить в config.yaml:**
```yaml
config_url: "https://gist.githubusercontent.com/.../raw/config.json"
```

3. **Запустить:**
```bash
python batch_processor.py
```

4. **Видеть merge:**
```
📥 Downloading remote config...
✓ Remote config merged: ['video']
  video params: {'input_dir': 'input/urgent', ...}
```

**Готово!** 🎉

---

**Remote config support полностью готов к использованию!**

Дата: 1 декабря 2025  
Версия: 1.0

