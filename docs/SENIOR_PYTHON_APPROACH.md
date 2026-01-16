# Senior Python Approach to CUDA Extension Management

## Проблема предыдущего решения

### ❌ Что было не так:

1. **entrypoint.sh не запускается в SSH режиме**
   - На Vast.ai при SSH подключении контейнер уже запущен
   - entrypoint.sh выполняется только при старте контейнера
   - Validation не происходит при прямом запуске Python

2. **Патчинг сторонних библиотек - антипаттерн**
   - Monkey patching ProPainter код
   - Модификация `/opt/ProPainter/RAFT/raft.py` в runtime
   - Непредсказуемое поведение при обновлениях
   - Технический долг

3. **Runtime rebuild - ненадежно**
   - Может не работать в production
   - Добавляет 60+ секунд к старту
   - Требует build tools в production образе
   - Может упасть на permission errors

## ✅ Правильное решение (Senior Python)

### Архитектурные принципы:

1. **Composition over Patching**
   - Не патчим код ProPainter
   - Создаем wrapper вокруг RAFT
   - Используем dependency injection

2. **Fail Fast Philosophy**
   - Валидация при старте приложения
   - Не ждем первого использования
   - Четкие error messages

3. **EAFP vs LBYL Balance**
   - EAFP для runtime checks (try-except)
   - LBYL для startup validation (check before use)

4. **Single Responsibility**
   - Каждый модуль делает одну вещь хорошо
   - Четкое разделение concerns

### Структура решения:

```
src/infrastructure/
├── startup.py                  # Application-level validation hooks
├── inpainting/
│   ├── raft_wrapper.py        # Wrapper around ProPainter RAFT
│   └── propainter_adapter.py  # Uses wrapper, not subprocess hacks
```

## Как это работает

### 1. RAFT Wrapper (`raft_wrapper.py`)

**Что делает:**
- Проверяет spatial-correlation-sampler без subprocess
- Предоставляет lazy initialization
- Graceful degradation с понятными ошибками
- Опциональный auto-rebuild (с env var)

**Паттерны:**
```python
# Lazy initialization
wrapper = ProPainterRAFTWrapper()
raft = wrapper.get_raft()  # Инициализация только при первом вызове

# Explicit checking
is_working, error = check_spatial_correlation_sampler()
if not is_working:
    # Handle error with clear message
    raise SpatialCorrelationSamplerError(error)

# Dependency injection
wrapper = ProPainterRAFTWrapper(propainter_root='/custom/path')
```

**Преимущества:**
- Нет subprocess overhead
- Нет monkey patching
- Testable (можно mock)
- Configurable (env vars, parameters)

### 2. Startup Hooks (`startup.py`)

**Что делает:**
- Валидация при старте приложения
- Работает всегда (entrypoint, SSH, прямой запуск)
- Fail fast с actionable errors
- Опциональный auto-rebuild

**Интеграция в приложение:**
```python
# В main entry point (cli.py)
from src.infrastructure.startup import startup_checks

def main():
    # Валидация перед любой обработкой
    startup_checks()
    
    # Дальше обычная логика
    ...
```

**Преимущества:**
- Всегда выполняется
- Независимо от способа запуска
- Четкие error messages
- Можно отключить (--skip-cuda-check)

### 3. CLI Integration (`cli.py`)

**Что добавлено:**
```python
# Новый аргумент
parser.add_argument('--skip-cuda-check', action='store_true',
                   help='Skip CUDA validation (NOT recommended)')

# Validation перед обработкой
if not args.skip_cuda_check:
    startup_checks()  # Fail fast если broken
```

**Преимущества:**
- Валидация при КАЖДОМ запуске
- SSH, entrypoint, direct Python - работает везде
- Можно отключить для debugging
- Четкие error messages

## Сценарии использования

### Сценарий 1: Docker Container Start
```bash
docker run your-image python pipeline_v2.py --input video.mp4

# Что происходит:
# 1. CLI парсит аргументы
# 2. setup_logger() настраивает логи
# 3. startup_checks() валидирует CUDA
# 4. Если ошибка → exit(1) с понятным сообщением
# 5. Если ок → обработка видео
```

### Сценарий 2: SSH в Running Container
```bash
ssh root@instance.vast.ai
python pipeline_v2.py --input video.mp4

# Что происходит:
# То же самое! entrypoint.sh не нужен
# startup_checks() выполняется в main()
```

### Сценарий 3: Interactive Python
```python
# python3
from src.infrastructure.startup import startup_checks
startup_checks()  # Проверка перед работой

# Дальше можно работать с RAFT
from src.infrastructure.inpainting.raft_wrapper import get_raft_wrapper
raft = get_raft_wrapper().get_raft()
```

### Сценарий 4: Auto-Rebuild (опционально)
```bash
export AUTO_REBUILD_CUDA_EXTENSIONS=true
python pipeline_v2.py --input video.mp4

# Если spatial-correlation-sampler broken:
# 1. Detect проблему
# 2. Попытка rebuild (~60 секунд)
# 3. Если успех → продолжить
# 4. Если fail → exit с инструкциями
```

## Конфигурация

### Environment Variables

**AUTO_REBUILD_CUDA_EXTENSIONS** (default: false)
```bash
export AUTO_REBUILD_CUDA_EXTENSIONS=true  # Включить auto-rebuild
```
⚠️ НЕ рекомендуется для production!

**PROPAINTER_ROOT** (default: /opt/ProPainter)
```bash
export PROPAINTER_ROOT=/custom/path/to/ProPainter
```

### CLI Arguments

**--skip-cuda-check**
```bash
python pipeline_v2.py --skip-cuda-check --input video.mp4
```
⚠️ Только для debugging!

**--verbose, -v**
```bash
python pipeline_v2.py -v --input video.mp4
```
Detailed validation logs.

## Error Messages

### Если spatial-correlation-sampler broken:

```
================================================================================
CRITICAL: spatial-correlation-sampler is BROKEN
================================================================================

What this means:
  - Docker image was built with different CUDA version than runtime
  - ProPainter RAFT will NOT work
  - Video processing will FAIL

How to fix (in order of preference):

  1. REBUILD DOCKER IMAGE with correct CUDA version:
     docker build -t your-image:latest .

  2. Enable auto-rebuild (NOT recommended for production):
     export AUTO_REBUILD_CUDA_EXTENSIONS=true
     (adds ~60 seconds to startup time)

  3. Manual rebuild (for debugging):
     pip install --force-reinstall spatial-correlation-sampler

  4. Use different GPU instance with matching CUDA version

================================================================================
```

## Testing

### Unit Tests
```python
# tests/unit/test_raft_wrapper.py
def test_raft_wrapper_lazy_init():
    wrapper = ProPainterRAFTWrapper()
    assert wrapper._raft is None  # Not initialized yet
    
    raft = wrapper.get_raft()
    assert wrapper._raft is not None  # Now initialized

def test_raft_wrapper_error_handling():
    # Mock broken spatial-correlation-sampler
    with pytest.raises(SpatialCorrelationSamplerError):
        wrapper = ProPainterRAFTWrapper()
        wrapper.get_raft()
```

### Integration Tests
```python
# tests/integration/test_startup.py
def test_startup_checks_fail_on_broken_cuda():
    # Simulate broken CUDA environment
    with pytest.raises(RuntimeError):
        startup_checks()

def test_startup_checks_pass_on_working_cuda():
    # Normal environment
    startup_checks()  # Should not raise
```

## Migration Path

### От старого решения:

**1. Убрать entrypoint.sh validation (необязательно)**
```bash
# В entrypoint.sh можно оставить для compatibility
# Но основная валидация теперь в Python
```

**2. Удалить subprocess validation из propainter_adapter**
```python
# Было:
def _validate_propainter_raft(self):
    subprocess.run(['python3', 'test_script.py'])  # ❌

# Стало:
def _validate_raft_with_wrapper(self):
    from src.infrastructure.inpainting.raft_wrapper import validate_raft_availability
    validate_raft_availability()  # ✅
```

**3. Удалить monkey patching scripts**
```bash
rm docker/patches/propainter_raft_fix.py  # Больше не нужен
```

## Performance Impact

### Cold Start (первый запуск):
- **Без auto-rebuild:** +0.1s (validation check)
- **С auto-rebuild (если broken):** +60s (rebuild)

### Warm Start (последующие запуски):
- **Always:** +0.1s (validation check)

### Runtime:
- **Zero overhead** - validation только на старте

## Best Practices

### ✅ DO:
1. Rebuild Docker image для production
2. Использовать startup_checks() в main()
3. Fail fast с понятными error messages
4. Логировать validation results
5. Тестировать на целевой CUDA версии

### ❌ DON'T:
1. Полагаться на AUTO_REBUILD_CUDA_EXTENSIONS в production
2. Патчить сторонний код
3. Игнорировать validation errors
4. Использовать --skip-cuda-check без причины
5. Надеяться на entrypoint.sh в SSH режиме

## Rollout Strategy

### Phase 1: Add Wrapper (Non-Breaking)
```bash
git add src/infrastructure/inpainting/raft_wrapper.py
git add src/infrastructure/startup.py
git commit -m "feat: add proper RAFT wrapper (no breaking changes)"
```

### Phase 2: Integrate CLI (Breaking Change)
```bash
git add src/presentation/cli.py
git commit -m "feat: add startup validation in CLI (BREAKING)"
```

### Phase 3: Deprecate Old Approach
```bash
# Remove subprocess validation from propainter_adapter
# Remove entrypoint.sh CUDA checks (optional)
git commit -m "refactor: remove deprecated subprocess validation"
```

### Phase 4: Cleanup
```bash
rm docker/patches/propainter_raft_fix.py
git commit -m "chore: remove unused patch scripts"
```

## Conclusion

Этот подход следует Python best practices:

- **Explicit is better than implicit** (PEP 20)
- **Errors should never pass silently** (PEP 20)
- **Composition over inheritance/patching**
- **Dependency injection for testability**
- **Fail fast principle**
- **Clear error messages**

Результат:
- ✅ Работает в SSH режиме
- ✅ Работает в любом режиме запуска
- ✅ Нет monkey patching
- ✅ Testable и maintainable
- ✅ Clear error handling
- ✅ Senior-level код

## References

- PEP 20 - The Zen of Python
- Composition over Inheritance
- Dependency Injection Pattern
- Fail Fast Principle
- SOLID Principles

