# Архитектурный анализ и рекомендации по оптимизации модуля генерации видео

## Резюме текущего состояния

### ✅ Существующая инфраструктура (переиспользуется)
- **Storage**: `src/infrastructure/storage/b2_client.py` - полнофункциональный S3/B2/R2 клиент
- **Logging**: `src/shared/logging.py` - централизованное логирование
- **Domain Layer**: `src/domain/` - протоколы и исключения (SOLID принципы)
- **Testing**: `tests/` - структурированная система тестирования

### ❌ Требует реализации
- Весь модуль `src/services/generation/` (текущий код устаревший)
- Новый Docker образ `Dockerfile.gen` с изолированными зависимостями
- CLI entrypoint `src/entrypoints/run_gen.py`
- Комплект тестов для генерации

---

## Архитектурные решения

### 1. Strategy Pattern для разных режимов генерации

**Проблема**: Поддержка Text-to-Video и Image-to-Video в одном модуле

**Решение**: Абстрактный `BaseVideoEngine` с конкретными реализациями

```python
BaseVideoEngine (ABC)
    ├── CogVideoText2VideoEngine (T2V)
    └── CogVideoImage2VideoEngine (I2V)
```

**Преимущества**:
- Легко добавить новые режимы (V2V, ControlNet, etc.)
- Изоляция логики каждого режима
- Единый интерфейс для orchestrator'а

### 2. Dependency Injection для тестируемости

**Реализация**:
```python
class GenerationOrchestrator:
    def __init__(
        self,
        config: Optional[GenerationConfig] = None,
        b2_client: Optional[B2Client] = None
    ):
        self.config = config or GenerationConfig()
        self.b2_client = b2_client or B2Client()
```

**Преимущества**:
- Mock'и в unit тестах
- Гибкая конфигурация
- Тестирование без GPU/B2

### 3. Pydantic для валидации данных

**Модели**:
- `GenJob` - входная спецификация задачи
- `GenerationResult` - результат одной генерации
- `BatchGenerationResult` - результат батча

**Преимущества**:
- Автоматическая валидация JSON
- Type hints
- Документация через Field descriptions

### 4. Изоляция dependencies через отдельный Docker образ

**Конфликты**:
- Основное приложение: OpenCV + PaddleOCR
- Генерация: diffusers + transformers

**Решение**: `Dockerfile.gen` с минимальными зависимостями

---

## Критические оптимизации

### 1. Управление VRAM (24GB GPU)

**Проблема**: CogVideoX-5b требует ~20GB VRAM

**Решение** (приоритет HIGH):
```python
# В GenerationConfig
ENABLE_CPU_OFFLOAD: bool = True      # Перемещение неиспользуемых слоев на CPU
ENABLE_VAE_SLICING: bool = True      # Обработка VAE по частям
ENABLE_TILING: bool = True           # Обработка изображений тайлами
USE_BFLOAT16: bool = True           # bf16 вместо fp32 (-30% VRAM)
```

**Ожидаемый эффект**: 
- Без оптимизаций: OOM на 24GB
- С оптимизациями: ~18GB usage + возможность batch=2

### 2. Ускорение inference

**Техники**:
```python
USE_XFORMERS: bool = True           # Memory-efficient attention (-20% время)
```

**Дополнительно (Phase 2)**:
```python
USE_TORCH_COMPILE: bool = True      # PyTorch 2.2+ compile (+30% после warmup)
USE_FLASH_ATTENTION_2: bool = True  # Требует flash-attn>=2.0
```

**Benchmarks** (примерные):
- Baseline (fp32): ~120 сек / видео
- bf16 + xformers: ~75 сек / видео
- + torch.compile: ~55 сек / видео

### 3. Safety Checker оптимизация

**Текущая проблема**: Проверка 3 фреймов через transformers pipeline на CPU

**Оптимизация (Phase 1)**:
- Проверять только средний фрейм (вместо 3х)
- Опциональный fast mode без проверки

**Оптимизация (Phase 2)**:
- Перенести на GPU
- Использовать легкую модель (MobileNet-based)

**Выигрыш**: -2-5 секунд на видео

### 4. Асинхронная загрузка в B2

**Проблема**: Upload блокирует генерацию следующего видео

**Решение (Phase 2)**:
```python
# Pipeline pattern
Queue: Generation → Safety Check → Upload
       (GPU)         (CPU)          (I/O)
```

**Реализация**:
- `asyncio` с queues
- `aioboto3` для async upload
- Background workers

**Выигрыш**: Параллелизация I/O и compute

### 5. Model warmup

**Проблема**: Первая генерация медленнее на 20-30%

**Решение**:
```python
def initialize(self) -> None:
    self.pipe = CogVideoXPipeline.from_pretrained(...)
    
    # Warmup с dummy prompt
    _ = self.pipe(
        "warmup",
        num_inference_steps=1,
        num_frames=9
    )
```

---

## Масштабируемость

### Поддержка batch inference

**Текущая реализация**: Последовательная обработка промптов

**Оптимизация (Phase 2)**:
```python
# В engine
def generate_batch(
    self,
    prompts: List[str],
    batch_size: int = 2  # Dynamic based on VRAM
) -> List[Path]
```

**Adaptive batching**:
```python
def _calculate_optimal_batch_size(self) -> int:
    """Динамическое определение batch size по доступной VRAM"""
    available_vram = torch.cuda.mem_get_info()[0]
    if available_vram > 20_000_000_000:  # 20GB
        return 2
    else:
        return 1
```

### Multi-GPU support (Future)

**Для production с несколькими GPU**:
```python
class MultiGPUOrchestrator:
    def __init__(self, gpu_ids: List[int]):
        self.engines = {
            gpu_id: CogVideoEngine(device=f"cuda:{gpu_id}")
            for gpu_id in gpu_ids
        }
    
    def distribute_jobs(self, job: GenJob):
        # Round-robin или load balancing
        pass
```

---

## Monitoring & Observability (Phase 3)

### Метрики

```python
# src/services/generation/metrics.py
class GenerationMetrics:
    generation_duration_seconds: Histogram
    gpu_memory_usage_bytes: Gauge
    queue_size: Gauge
    success_rate: Counter
    nsfw_detections: Counter
```

### Интеграция

- Prometheus metrics endpoint
- Structured logging (JSON)
- Distributed tracing (OpenTelemetry)

---

## Тестовая стратегия

### Пирамида тестов

```
           /\
          /  \  E2E (GPU required)
         /____\
        /      \  Integration (mocked GPU)
       /________\
      /          \  Unit tests (fast, no GPU)
     /____________\
```

### Покрытие

**Unit tests** (~70% покрытия):
- Config loading
- Model validation
- Engine logic (mocked pipeline)
- Orchestrator flow (mocked engines)

**Integration tests** (~20% покрытия):
- E2E workflow с моками
- B2 upload (mocked)
- Error scenarios

**GPU tests** (~10% покрытия):
- Реальная генерация (CI skip, manual run)
- Performance benchmarks

### Маркировка тестов

```python
@pytest.mark.unit         # Быстрые, без GPU
@pytest.mark.integration  # С моками
@pytest.mark.gpu          # Требует GPU
@pytest.mark.slow         # Длинные тесты
```

---

## CI/CD стратегия

### GitHub Actions / GitLab CI

```yaml
stages:
  - test:unit        # Всегда запускается
  - test:integration # Всегда запускается
  - build:docker     # На main branch
  - test:gpu         # Manual / scheduled (Vast.ai runner)
```

### Docker Registry

- Development: `ghcr.io/user/video-gen:dev`
- Production: `ghcr.io/user/video-gen:v1.0.0`
- Model cache: Pre-baked images с моделями

---

## Security & Safety

### 1. Input validation

```python
# В GenJob
@validator('prompts')
def validate_prompts(cls, v):
    # Проверка на injection
    dangerous_tokens = ['<script>', '<?php', '{{', '{%']
    for prompt in v:
        if any(token in prompt.lower() for token in dangerous_tokens):
            raise ValueError("Dangerous tokens detected")
    return v
```

### 2. Rate limiting

```python
# В orchestrator
from src.shared.rate_limiter import RateLimiter

class GenerationOrchestrator:
    def __init__(self, ...):
        self.rate_limiter = RateLimiter(
            max_requests_per_minute=10,
            max_requests_per_hour=100
        )
```

### 3. Resource limits

```python
# В config
MAX_INFERENCE_STEPS: int = 200      # Защита от abuse
MAX_NUM_FRAMES: int = 96            # Лимит длины видео
GENERATION_TIMEOUT: int = 600       # 10 минут таймаут
```

---

## Cost optimization

### Vast.ai deployment

**Рекомендации**:
- Spot instances для экспериментов
- On-demand для production
- Auto-scaling по queue size

**Benchmark costs** (примерные):
```
RTX 3090 (24GB): ~$0.20/hour
- Генерация: ~75 сек/видео
- Cost per video: ~$0.004

RTX 4090 (24GB): ~$0.35/hour
- Генерация: ~50 сек/видео
- Cost per video: ~$0.005
```

### Эффективность

**Amortization через batch**:
- Model load: 30-60 сек (единожды)
- Generation: 50-75 сек/видео

**Оптимальный batch size**: 5-10 промптов на job для амортизации загрузки

---

## Roadmap приоритизации

### Phase 1: T2V MVP (2 недели) - CRITICAL
✅ Базовая функциональность
✅ Docker изоляция
✅ Unit tests
✅ VRAM оптимизации

### Phase 2: I2V + Performance (1 неделя) - HIGH
✅ Image-to-Video support
✅ Async upload
✅ Torch compile
✅ Integration tests

### Phase 3: Production готовность (1 неделя) - MEDIUM
✅ Monitoring
✅ Advanced batching
✅ Error recovery
✅ Load tests

### Phase 4: Advanced features (Future) - LOW
- Multi-GPU
- LoRA support
- ControlNet integration
- REST API

---

## Заключение

### Ключевые решения

1. **Архитектура**: Strategy pattern + DI = расширяемость и тестируемость
2. **Изоляция**: Отдельный Docker образ = no conflicts
3. **Оптимизация**: VRAM management = работа на 24GB GPU
4. **Переиспользование**: B2 client + logging = меньше кода

### Риски и митигация

| Риск | Вероятность | Impact | Митигация |
|------|-------------|--------|-----------|
| OOM на 24GB | Высокая | Критический | CPU offload + VAE slicing обязательны |
| Медленная генерация | Средняя | Высокий | xformers + bf16 в Phase 1, torch.compile в Phase 2 |
| NSFW content | Средняя | Средний | Safety checker с tuned threshold |
| Зависимость от Vast.ai | Низкая | Средний | Мультиоблачная стратегия (RunPod, Lambda) |

### Next Steps

1. ✅ **Документация**: README + Implementation Plan готовы
2. 🔨 **Реализация**: Начать с Domain Layer (protocols)
3. 🧪 **Тесты**: TDD approach - tests first, implementation second
4. 🐳 **Docker**: Parallel - подготовить Dockerfile.gen
5. 🚀 **Deploy**: После Phase 1 - первый deploy на Vast.ai

---

**Ссылки**:
- [Implementation Plan](./IMPLEMENTATION_PLAN_GENERATION.md) - детальный план реализации
- [README](./README_GENERATION.md) - документация по использованию
- [Complete Architecture](./COMPLETE_ARCHITECTURE_DOCUMENTATION.md) - общая архитектура проекта
