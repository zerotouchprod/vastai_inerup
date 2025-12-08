# План Удаления Legacy Кода

**Дата**: 8 декабря 2025  
**Цель**: Полностью удалить старый pipeline.py и bash скрипты, оставить только pipeline_v2.py с native Python processors

---

## 📊 Текущая Ситуация

### ✅ Новая Архитектура (Работает!)
```
pipeline_v2.py
    ↓
src/presentation/cli.py
    ↓
src/application/orchestrator.py
    ↓
src/infrastructure/processors/
    ├── realesrgan/native.py (750 строк Python)
    └── rife/native.py (750 строк Python)
```

**Преимущества**:
- ✅ Clean Architecture (SOLID)
- ✅ Full debugging в PyCharm
- ✅ 78 unit тестов
- ✅ USE_NATIVE_PROCESSORS=1 по умолчанию

---

### ❌ Legacy Код (К УДАЛЕНИЮ)

```
pipeline.py (900 строк)
    ↓
run_realesrgan_pytorch.sh (977 строк bash)
    ↓
realesrgan_batch_safe.sh (~500 строк bash)

pipeline.py
    ↓
run_rife_pytorch.sh (1,097 строк bash)
```

**Проблемы**:
- ❌ Сложно отлаживать (bash)
- ❌ Monolithic код
- ❌ Нет тестов
- ❌ Tight coupling

---

## 📋 Файлы для Удаления

### 1. Legacy Pipeline
```bash
pipeline.py                    # 900 строк - старый entry point
```

### 2. Bash Wrappers
```bash
run_realesrgan_pytorch.sh      # 977 строк - обертка для Real-ESRGAN
run_rife_pytorch.sh            # 1,097 строк - обертка для RIFE
realesrgan_batch_safe.sh       # ~500 строк - batch обработка
```

**Итого**: ~3,474 строки bash кода → УДАЛИТЬ

---

## 🔍 Зависимости (Что Нужно Исправить)

### 1. **scripts/container_config_runner.py** ⚠️
**Текущий код** (строки 479-485):
```python
# Use pipeline_v2.py (new architecture with native Python support)
pipeline_script = '/workspace/project/pipeline_v2.py'
if not os.path.exists(pipeline_script):
    # Fallback to old pipeline.py if v2 not present
    pipeline_script = '/workspace/project/pipeline.py'
    print(f"⚠️  Warning: pipeline_v2.py not found, using legacy pipeline.py")
```

**Проблема**: Есть fallback на pipeline.py

**Решение**: Удалить fallback, требовать pipeline_v2.py

---

### 2. **scripts/remote_runner.sh** ⚠️
**Текущий код** (проверяет существование bash скриптов):
```bash
echo "[remote_runner] Checking for PyTorch wrapper scripts and ncnn binaries:"
if [ -x "/workspace/project/run_realesrgan_pytorch.sh" ]; then 
    echo "  run_realesrgan_pytorch.sh: exists+executable"
else 
    echo "  run_realesrgan_pytorch.sh: missing or not executable"
fi

if [ -x "/workspace/project/run_rife_pytorch.sh" ]; then 
    echo "  run_rife_pytorch.sh: exists+executable"
else 
    echo "  run_rife_pytorch.sh: missing or not executable"
fi

# Ensure wrapper scripts are executable
if [ -f "/workspace/project/run_realesrgan_pytorch.sh" ]; then
  chmod +x /workspace/project/run_realesrgan_pytorch.sh || true
fi

if [ -f "/workspace/project/run_rife_pytorch.sh" ]; then
  chmod +x /workspace/project/run_rife_pytorch.sh || true
fi
```

**Проблема**: Скрипт ищет и делает executable bash файлы

**Решение**: Удалить эти проверки, они больше не нужны

---

### 3. **src/infrastructure/processors/*/pytorch_wrapper.py** ⚠️
**Файлы**:
- `src/infrastructure/processors/realesrgan/pytorch_wrapper.py`
- `src/infrastructure/processors/rife/pytorch_wrapper.py`

**Текущий код**:
```python
WRAPPER_SCRIPT = Path("/workspace/project/run_realesrgan_pytorch.sh")
```

**Проблема**: Ссылаются на bash скрипты

**Решение**: 
- **Вариант 1**: Удалить эти файлы полностью (native processors работают)
- **Вариант 2**: Оставить как deprecated (добавить warning)

---

### 4. **Документация** 📚
**Файлы с упоминаниями legacy кода**:
- `docs/BOTH_MODE_FIX.md`
- `docs/DEBUG_IMPROVEMENT_PLAN.md`
- `docs/DEBUG_MODE_GUIDE.md`
- `docs/DOCKER_NATIVE_NO_REBUILD.md`
- `docs/FINAL_READY_TO_DEPLOY.md`
- `docs/FINAL_REPORT.md`
- `docs/FIX_UINT16_CONVERSION.md`
- `docs/MASTER_SUMMARY.md`
- `docs/NATIVE_PROCESSORS_GUIDE.md`
- `docs/oop2.md`
- `docs/oop3.md`
- `docs/QUICKSTART.md`
- `docs/REFACTORING_COMPLETE.md`
- `docs/SHELL_SCRIPTS_ANALYSIS.md`
- `docs/SHELL_SCRIPTS_VERDICT.md`
- `docs/SHELL_TO_PYTHON_COMPLETE.md`
- `TODO.md`

**Решение**: Добавить примечания "УСТАРЕЛО - используйте pipeline_v2.py"

---

## 🚀 План Миграции (5 Шагов)

### ✅ Шаг 1: Проверка Готовности
**Что проверить**:
- [ ] pipeline_v2.py существует и работает
- [ ] Native processors протестированы
- [ ] container_config_runner.py использует pipeline_v2.py
- [ ] USE_NATIVE_PROCESSORS=1 установлен по умолчанию
- [ ] Все тесты проходят

**Команда**:
```bash
# Проверить что pipeline_v2.py работает
python pipeline_v2.py --help

# Запустить тесты
pytest tests/ -v

# Проверить что USE_NATIVE_PROCESSORS работает
export USE_NATIVE_PROCESSORS=1
python pipeline_v2.py --mode upscale --input test.mp4 --output output/ --scale 2
```

---

### 📝 Шаг 2: Обновить Production Scripts

#### 2.1. Обновить container_config_runner.py
**Удалить fallback на pipeline.py**:

```python
# СТАРЫЙ КОД (УДАЛИТЬ):
pipeline_script = '/workspace/project/pipeline_v2.py'
if not os.path.exists(pipeline_script):
    # Fallback to old pipeline.py if v2 not present
    pipeline_script = '/workspace/project/pipeline.py'
    print(f"⚠️  Warning: pipeline_v2.py not found, using legacy pipeline.py")

# НОВЫЙ КОД:
pipeline_script = '/workspace/project/pipeline_v2.py'
if not os.path.exists(pipeline_script):
    print(f"❌ ERROR: pipeline_v2.py not found!")
    print(f"Legacy pipeline.py has been removed.")
    print(f"Please ensure your Git repo is up to date.")
    sys.exit(1)
```

#### 2.2. Обновить remote_runner.sh
**Удалить проверки bash скриптов**:

```bash
# УДАЛИТЬ ВСЕ ЭТИ СТРОКИ:
if [ -x "/workspace/project/run_realesrgan_pytorch.sh" ]; then...
if [ -x "/workspace/project/run_rife_pytorch.sh" ]; then...
if [ -f "/workspace/project/run_realesrgan_pytorch.sh" ]; then chmod +x...
if [ -f "/workspace/project/run_rife_pytorch.sh" ]; then chmod +x...

# ДОБАВИТЬ:
echo "[remote_runner] Using pipeline_v2.py with native Python processors"
```

---

### 🗑️ Шаг 3: Удалить Legacy Файлы

```bash
# Перейти в корень проекта
cd /d/PycharmProjects/vastai_inerup_ztp

# Удалить legacy pipeline
git rm pipeline.py

# Удалить bash wrappers
git rm run_realesrgan_pytorch.sh
git rm run_rife_pytorch.sh
git rm realesrgan_batch_safe.sh

# Удалить deprecated pytorch_wrapper.py (опционально)
git rm src/infrastructure/processors/realesrgan/pytorch_wrapper.py
git rm src/infrastructure/processors/rife/pytorch_wrapper.py

# Коммит
git commit -m "refactor: remove legacy pipeline.py and bash wrappers

- Removed pipeline.py (900 lines)
- Removed run_realesrgan_pytorch.sh (977 lines)
- Removed run_rife_pytorch.sh (1,097 lines)
- Removed realesrgan_batch_safe.sh (~500 lines)
- Removed pytorch_wrapper.py files (deprecated)

Total: ~3,500 lines of legacy code removed

✅ pipeline_v2.py is now the only entry point
✅ Native Python processors are used by default
✅ Full debugging support in PyCharm
✅ Clean Architecture maintained"
```

---

### 📚 Шаг 4: Обновить Документацию

#### 4.1. Обновить README.md
Добавить секцию "Migration from Legacy":

```markdown
## 🔄 Migration from Legacy (Dec 2025)

**ВАЖНО**: `pipeline.py` и bash скрипты удалены!

### Что изменилось:
- ❌ `pipeline.py` (удален)
- ❌ `run_realesrgan_pytorch.sh` (удален)
- ❌ `run_rife_pytorch.sh` (удален)
- ❌ `realesrgan_batch_safe.sh` (удален)

### Что использовать:
- ✅ `pipeline_v2.py` (единственная точка входа)
- ✅ Native Python processors (по умолчанию)

### Как запускать:
```bash
# Старый способ (НЕ РАБОТАЕТ):
python pipeline.py --input video.mp4 --output output/

# Новый способ (ИСПОЛЬЗУЙТЕ):
python pipeline_v2.py --input video.mp4 --output output/
```
```

#### 4.2. Добавить DEPRECATED.md
Создать файл с историей:

```markdown
# Deprecated Legacy Code (Removed Dec 2025)

This file documents legacy code that was removed in December 2025.

## Removed Files

### 1. pipeline.py
- **Size**: 900 lines
- **Replaced by**: pipeline_v2.py
- **Reason**: Monolithic, hard to debug, no tests

### 2. Bash Wrappers
- `run_realesrgan_pytorch.sh` (977 lines)
- `run_rife_pytorch.sh` (1,097 lines)
- `realesrgan_batch_safe.sh` (~500 lines)
- **Replaced by**: Native Python processors
- **Reason**: Bash is hard to debug, no breakpoints

## Migration Guide

See README.md section "Migration from Legacy".
```

#### 4.3. Обновить старую документацию
В начало всех файлов с упоминаниями legacy:

```markdown
---
⚠️ **УСТАРЕЛО**: Этот документ содержит ссылки на legacy код (pipeline.py, bash скрипты).
Legacy код удален в декабре 2025. Используйте `pipeline_v2.py` с native Python processors.
См. README.md для актуальной информации.
---
```

---

### ✅ Шаг 5: Тестирование После Удаления

```bash
# 1. Unit тесты
pytest tests/unit/ -v

# 2. Integration тесты
pytest tests/integration/ -v

# 3. Smoke test с реальным видео
python pipeline_v2.py --mode upscale --input test.mp4 --output output/ --scale 2

# 4. Проверить что USE_NATIVE_PROCESSORS работает
export USE_NATIVE_PROCESSORS=1
export DEBUG_PROCESSORS=1
python pipeline_v2.py --mode both --input test.mp4 --output output/

# 5. Проверить container_config_runner.py
python scripts/container_config_runner.py config.yaml
```

---

## 📊 Результат

### До Очистки:
```
Код:
- pipeline.py: 900 строк
- bash скрипты: ~2,574 строк
- pytorch_wrapper.py: ~200 строк
Итого: ~3,674 строки legacy кода
```

### После Очистки:
```
Код:
- pipeline_v2.py: 20 строк (entry point)
- src/: ~4,500 строк (Clean Architecture)
- Native processors: ~1,500 строк
Итого: ~6,000 строк чистого Python + SOLID
```

### Преимущества:
- ✅ **-3,674 строки** legacy кода удалено
- ✅ **100% Python** - нет bash зависимостей
- ✅ **Full debugging** - breakpoints работают
- ✅ **Clean Architecture** - SOLID принципы
- ✅ **78 тестов** - высокое покрытие
- ✅ **Понятная структура** - легко расширять

---

## ⚠️ Риски и Митигация

### Риск 1: Кто-то использует старый pipeline.py
**Вероятность**: Низкая (v2 предпочтителен)  
**Митигация**: 
- container_config_runner.py показывает ошибку с инструкциями
- Документация обновлена
- README.md содержит migration guide

### Риск 2: Старые Docker образы
**Вероятность**: Средняя  
**Митигация**: 
- Пересобрать Docker образы после удаления
- Обновить CI/CD pipelines
- Документировать в Dockerfile

### Риск 3: Потеря истории изменений
**Вероятность**: Низкая (git хранит историю)  
**Митигация**: 
- Git история сохраняется (git log pipeline.py все еще работает)
- DEPRECATED.md документирует удаленные файлы
- Тэг перед удалением: `git tag legacy-before-cleanup`

---

## 🎯 Чеклист Перед Удалением

- [ ] Все тесты проходят (`pytest tests/ -v`)
- [ ] pipeline_v2.py работает для всех режимов (upscale, interp, both)
- [ ] Native processors протестированы
- [ ] container_config_runner.py обновлен (нет fallback)
- [ ] remote_runner.sh обновлен (нет проверок bash)
- [ ] Документация обновлена
- [ ] Создан git тэг: `git tag legacy-before-cleanup`
- [ ] README.md содержит migration guide
- [ ] DEPRECATED.md создан
- [ ] Docker образы пересобраны (после удаления)

---

## 📅 Timeline

1. **Сегодня (8 дек 2025)**: Создать план (этот документ) ✅
2. **Сегодня**: Обновить production scripts
3. **Сегодня**: Удалить legacy файлы
4. **Завтра**: Обновить документацию
5. **Завтра**: Тестирование + пересборка Docker
6. **Послезавтра**: Deploy в production

---

## 🎉 Success Criteria

- ✅ Legacy код удален (>3,500 строк)
- ✅ Все тесты проходят
- ✅ pipeline_v2.py - единственная точка входа
- ✅ Native processors работают по умолчанию
- ✅ Full debugging в PyCharm
- ✅ Документация актуальна
- ✅ Production не сломан

---

**Готовы начать?** Следуйте шагам выше! 🚀
