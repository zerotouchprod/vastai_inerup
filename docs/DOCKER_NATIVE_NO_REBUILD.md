# ✅ Docker без пересборки - Native Processors включены!

**1 декабря 2025** - Настройка удалённого runner для использования native Python

---

## 🎯 Задача

> Сейчас Docker запускается с `entrypoint.sh` → `remote_runner.sh`  
> Мне надо чтобы использовался новый код без пересборки образа `Dockerfile.pytorch.fat`

---

## ✅ РЕШЕНИЕ ГОТОВО!

### Что сделано (2 простых изменения):

### 1️⃣ Обновлён `scripts/remote_runner.sh` ✅

**Добавлено в начало скрипта**:
```bash
# 🐍 USE NATIVE PYTHON PROCESSORS (no shell scripts!)
export USE_NATIVE_PROCESSORS=${USE_NATIVE_PROCESSORS:-1}

echo "=== Remote Runner Starting ==="
if [ "$USE_NATIVE_PROCESSORS" = "1" ]; then
  echo "🐍 Native Python processors ENABLED"
  echo "   → Full debugging support"
  echo "   → 100% Python code"
else
  echo "🐚 Shell-based processors (legacy mode)"
fi
```

### 2️⃣ Обновлён `scripts/container_config_runner.py` ✅

**Изменено**:
1. Использует `pipeline_v2.py` вместо старого `pipeline.py`
2. Передаёт `USE_NATIVE_PROCESSORS=1` в env при запуске

```python
# Use pipeline_v2.py (new architecture with native Python support)
pipeline_script = '/workspace/project/pipeline_v2.py'

env = os.environ.copy()
env['PYTHONUNBUFFERED'] = '1'

# 🐍 Use native Python processors
if 'USE_NATIVE_PROCESSORS' not in env:
    env['USE_NATIVE_PROCESSORS'] = '1'
```

---

## 🔄 Как это работает

### Цепочка вызовов:

```
entrypoint.sh
    ↓
remote_runner.sh
    ↓ (export USE_NATIVE_PROCESSORS=1)
container_config_runner.py
    ↓ (env['USE_NATIVE_PROCESSORS'] = '1')
pipeline_v2.py
    ↓ (sys.path + src/)
presentation.cli.main()
    ↓
ProcessorFactory()
    ↓ (reads USE_NATIVE_PROCESSORS from ENV)
🐍 Native Python Processors!
```

---

## ✅ Преимущества

### Без пересборки Docker! ✅
```bash
# Просто запушить изменённые файлы:
git add scripts/remote_runner.sh
git add scripts/container_config_runner.py
git commit -m "Enable native Python processors"
git push

# Контейнер подтянет изменения через entrypoint.sh!
```

### Автоматическое обновление ✅
```bash
# entrypoint.sh делает git pull на каждом запуске
# → Новый код применится без пересборки!
```

### Можно отключить при необходимости ✅
```bash
# В job environment на vast.ai:
export USE_NATIVE_PROCESSORS=0

# → Вернётся к shell wrappers
```

---

## 📊 Что изменилось в контейнере

### Было (Shell wrappers):
```
remote_runner.sh
    → container_config_runner.py
        → pipeline.py (старая версия)
            → run_realesrgan_pytorch.sh (977 строк bash)
            → run_rife_pytorch.sh (1,097 строк bash)
```

### Стало (Native Python):
```
remote_runner.sh (USE_NATIVE_PROCESSORS=1)
    → container_config_runner.py
        → pipeline_v2.py (новая архитектура)
            → ProcessorFactory (use_native=True)
                → RealESRGANNative (400 строк Python) ✅
                → RIFENative (350 строк Python) ✅
```

---

## 🚀 Deployment

### Шаг 1: Commit изменения
```bash
git add scripts/remote_runner.sh
git add scripts/container_config_runner.py
git commit -m "feat: enable native Python processors without Docker rebuild"
git push origin main
```

### Шаг 2: Запустить контейнер
```bash
# На vast.ai - просто запустить instance
# entrypoint.sh автоматически:
# 1. git pull (подтянет новый код)
# 2. запустит remote_runner.sh
# 3. USE_NATIVE_PROCESSORS=1 уже установлен!
```

### Шаг 3: Проверить логи
```bash
# В логах контейнера увидите:
=== Remote Runner Starting ===
🐍 Native Python processors ENABLED (no bash scripts)
   → Full debugging support
   → 100% Python code
```

---

## 🔧 Проверка

### Проверить что native используется:

**В логах контейнера**:
```
🐍 Native Python processors ENABLED
...
🐍 Using NATIVE Python processors (no shell scripts)
```

**Если видите**:
```
🐚 Shell-based processors (legacy mode)
```
→ Значит `USE_NATIVE_PROCESSORS` не установлен (проверить файлы)

---

## 💡 Дополнительные опции

### Включить debug mode:
```bash
# В job env на vast.ai:
export USE_NATIVE_PROCESSORS=1
export DEBUG_PROCESSORS=1

# → Получите native + детальные логи!
```

### Использовать старые wrappers:
```bash
# Если native не работает:
export USE_NATIVE_PROCESSORS=0

# → Вернётся к проверенным shell скриптам
```

### Принудительный software encoding:
```bash
export FORCE_SW_ENC=1

# → libx264 вместо NVENC (если проблемы с GPU)
```

---

## 📝 Файлы изменены

### Обновлены (2):
1. ✅ `scripts/remote_runner.sh` (+10 строк)
2. ✅ `scripts/container_config_runner.py` (+10 строк)

### Используют новый код:
3. ✅ `pipeline_v2.py` (уже был)
4. ✅ `src/application/factories.py` (уже был)
5. ✅ `src/infrastructure/processors/*/native.py` (уже были)

---

## 🎉 Результат

### ✅ Что достигнуто:

- ✅ **Без пересборки Docker образа**
- ✅ **Native Python processors включены по умолчанию**
- ✅ **Автоматическое обновление через Git**
- ✅ **Можно переключаться между native/shell**
- ✅ **Обратная совместимость сохранена**

### 🐍 Преимущества native:

- ✅ 2,074 строки bash → 750 строк Python
- ✅ Full debugging support
- ✅ Понятный код
- ✅ Легко расширять
- ✅ 100% Python

---

## 🎯 Следующие шаги

### Сейчас:
```bash
# 1. Push изменения
git push

# 2. Запустить job на vast.ai
# → Автоматически использует native!

# 3. Смотреть логи
# → Видеть "🐍 Native Python processors ENABLED"
```

### Если что-то не так:
```bash
# Быстро откатиться:
export USE_NATIVE_PROCESSORS=0

# → Shell wrappers (stable)
```

---

**СТАТУС**: ✅ **ГОТОВО**

**Без пересборки Docker!** Просто git push! 🚀

*Настройка завершена: 1 декабря 2025*

