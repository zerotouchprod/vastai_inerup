# Implementation Plan: Text-to-Video & Image-to-Video Generation

**Дата создания:** 2 февраля 2026  
**Статус:** В разработке  
**Цель:** Реализация полноценного модуля генерации видео с поддержкой Text-to-Video и Image-to-Video

---

## 📋 Оглавление

1. [Текущее состояние](#текущее-состояние)
2. [Архитектурный анализ](#архитектурный-анализ)
3. [Фаза 1: Text-to-Video (T2V)](#фаза-1-text-to-video-t2v)
4. [Фаза 2: Image-to-Video (I2V)](#фаза-2-image-to-video-i2v)
5. [Тестирование](#тестирование)
6. [Deployment & CI/CD](#deployment--cicd)
7. [Метрики и мониторинг](#метрики-и-мониторинг)

---

## Текущее состояние

### ✅ Реализовано

#### Инфраструктура и общие компоненты
- ✅ **B2/S3 Storage Integration**: `src/infrastructure/storage/b2_client.py`
  - Upload/download с presigned URLs
  - Поддержка S3-compatible endpoints (Backblaze B2, R2, MinIO)
  - Retry механизм и error handling
  
- ✅ **Logging System**: `src/shared/logging.py`
  - Structured logging с rotation
  - JSON format для production
  - Debug mode для development

- ✅ **Domain Layer**: `src/domain/`
  - Протоколы и интерфейсы (`generation.py`, `exceptions.py`)
  - Clean Architecture принципы

#### Generation Module (Частично)
- ✅ **Configuration**: `src/services/generation/config.py`
  - Environment-based configuration
  - Validation и defaults
  - Optimization flags (CPU offload, VAE slicing, etc.)

- ✅ **Data Models**: `src/services/generation/models.py`
  - `GenJob` с валидацией
  - `GenerationResult`, `BatchGenerationResult`
  - `GenerationMode` enum (TEXT2VIDEO, IMAGE2VIDEO)

- ✅ **Base Engine**: `src/services/generation/engines/base.py`
  - Abstract base class для всех engine
  - Safety checker integration
  - Common utilities (export, generator creation)

- ✅ **Text2Video Engine (Skeleton)**: `src/services/generation/engines/text2video.py`
  - Базовая структура
  - Model loading logic
  - **НО:** использует старую модель `THUDM/CogVideoX-5b` (нужна `CogVideoX-5b-I2V`)

- ✅ **Orchestrator (Partial)**: `src/services/generation/orchestrator.py`
  - Job processing workflow
  - B2 upload integration
  - Batch processing logic

- ✅ **Docker Image**: `docker/Dockerfile.gen`
  - Multi-stage build
  - **✅ ОБНОВЛЕНО:** Встроенная модель `CogVideoX-5b-I2V` (baked model)
  - Offline mode (`HF_HUB_OFFLINE=1`)
  - Optimized для 24GB VRAM

### ❌ Отсутствует / Требует реализации

#### Критические компоненты
- ❌ **Image-to-Video Engine**: `src/services/generation/engines/image2video.py`
  - Класс не существует
  - Нужна реализация на базе `CogVideoX-5b-I2V`

- ❌ **Image Loader Utilities**: `src/services/generation/utils/image_loader.py`
  - Загрузка из URL
  - Base64 decoding
  - Local file reading
  - Validation (format, size, dimensions)

- ❌ **Entrypoint**: `src/entrypoints/run_gen.py`
  - CLI для запуска worker
  - JSON job parsing
  - Error handling и logging

#### Тестирование
- ❌ **Unit Tests**: `tests/unit/services/generation/`
  - Тесты для config, models, engines
  
- ❌ **Integration Tests**: `tests/integration/generation/`
  - End-to-end workflow тесты
  - Mocking HuggingFace models

---

## Архитектурный анализ

### 🏗️ Текущая архитектура

```
src/
├── domain/                          # Domain Layer (чистая бизнес-логика)
│   ├── generation.py               # Protocols: VideoEngineProtocol
│   └── exceptions.py               # Domain exceptions
│
├── services/generation/            # Application Layer
│   ├── config.py                   # Configuration (Environment-based)
│   ├── models.py                   # Pydantic models (GenJob, Result)
│   ├── orchestrator.py             # Main workflow orchestrator
│   ├── engines/                    # Strategy Pattern: разные режимы генерации
│   │   ├── base.py                 # BaseVideoEngine (abstract)
│   │   ├── text2video.py           # CogVideoX T2V
│   │   └── image2video.py          # [TO IMPLEMENT] CogVideoX I2V
│   └── utils/
│       └── image_loader.py         # [TO IMPLEMENT] Image loading utilities
│
├── infrastructure/                 # Infrastructure Layer
│   └── storage/
│       └── b2_client.py            # B2/S3 integration (переиспользуется)
│
├── shared/                         # Shared utilities
│   └── logging.py                  # Logging setup (переиспользуется)
│
└── entrypoints/                    # Entry points
    └── run_gen.py                  # [TO IMPLEMENT] CLI worker entrypoint
```

### ✅ Архитектурные принципы

#### 1. **Clean Architecture** (Соблюдается)
- **Domain Layer** не зависит от infrastructure
- **Application Layer** координирует workflow через orchestrator
- **Infrastructure Layer** реализует протоколы (B2Client)
- **Dependency Inversion**: Engine зависит от протокола, не от конкретной реализации

#### 2. **Strategy Pattern** (Применяется корректно)
- `BaseVideoEngine` — абстрактный класс
- `Text2VideoEngine`, `Image2VideoEngine` — конкретные стратегии
- `Orchestrator` выбирает engine на основе `GenerationMode`

#### 3. **SOLID Principles**
- ✅ **SRP**: Каждый класс имеет одну ответственность
  - `Config` — конфигурация
  - `Engine` — генерация
  - `Orchestrator` — координация
  - `B2Client` — storage
  
- ✅ **OCP**: Можно добавить новый engine без изменения orchestrator
- ✅ **LSP**: Все engines заменяемы (наследуют `BaseVideoEngine`)
- ✅ **ISP**: Протоколы разделены (`VideoEngineProtocol`, `StorageProtocol`)
- ✅ **DIP**: Orchestrator зависит от абстракций, не от конкретных классов

#### 4. **Fail-Safe Design**
- Batch processing продолжается при ошибке в одном промпте
- Safety checker fail-open (при ошибке пропускает контент)
- B2 upload optional (можно работать без загрузки)

---

## Фаза 1: Text-to-Video (T2V)

**Цель:** Реализовать полноценный T2V с моделью `CogVideoX-5b-I2V` (используется как T2V без референсной картинки)

### 🎯 Задачи

#### 1.1. Обновить Text2Video Engine для `CogVideoX-5b-I2V`

**Файл:** `src/services/generation/engines/text2video.py`

**Изменения:**
```python
# Было
self.model_id = self.config.T2V_MODEL_ID  # "THUDM/CogVideoX-5b"

# Стало (используем I2V модель для лучшего качества аниме)
self.model_id = "THUDM/CogVideoX-5b-I2V"
```

**Причина:** Модель `CogVideoX-5b-I2V` оптимизирована для аниме и может работать как T2V, если не передавать референсное изображение.

**Обоснование:**
- Лучшее качество для аниме стилизации
- Единая модель для T2V и I2V (экономия VRAM и времени загрузки)
- Уже встроена в Docker образ

#### 1.2. Реализовать Entrypoint `run_gen.py`

**Файл:** `src/entrypoints/run_gen.py`

**Функциональность:**
- Парсинг JSON job из CLI аргумента `--job`
- Создание `GenerationOrchestrator`
- Обработка job и вывод результата
- Error handling и graceful shutdown

**Пример использования:**
```bash
python -m src.entrypoints.run_gen --job '{
  "prompts": ["A cat dancing in the rain"],
  "guidance_scale": 7.0,
  "num_inference_steps": 40
}'
```

**Структура:**
```python
# src/entrypoints/run_gen.py
import argparse
import json
import sys
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.models import GenJob
from src.shared.logging import get_logger

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, help='JSON job specification')
    parser.add_argument('--no-upload', action='store_true', help='Skip B2 upload')
    parser.add_argument('--dry-run', action='store_true', help='Validate only')
    args = parser.parse_args()
    
    # Parse job
    job_data = json.loads(args.job)
    job = GenJob(**job_data)
    
    # Create orchestrator
    orchestrator = GenerationOrchestrator()
    
    # Process
    if args.dry_run:
        print(f"✓ Job validated: {job.id}")
        return 0
    
    result = orchestrator.process_job(job)
    
    # Output result
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.successful > 0 else 1

if __name__ == '__main__':
    sys.exit(main())
```

#### 1.3. Обновить конфигурацию

**Файл:** `src/services/generation/config.py`

**Изменения:**
```python
# Обновить дефолтную модель для T2V
T2V_MODEL_ID: str = "THUDM/CogVideoX-5b-I2V"  # Используем I2V модель
I2V_MODEL_ID: str = "THUDM/CogVideoX-5b-I2V"  # Та же модель
```

**Причина:** Единая модель для обоих режимов упрощает управление и экономит ресурсы.

---

## Фаза 2: Image-to-Video (I2V)

**Цель:** Реализовать I2V на базе той же модели `CogVideoX-5b-I2V`, добавив поддержку входных изображений.

### 🎯 Задачи

#### 2.1. Реализовать Image Loader

**Файл:** `src/services/generation/utils/image_loader.py`

**Функциональность:**
- Загрузка из URL (`https://...`)
- Декодирование base64 (`data:image/jpeg;base64,...`)
- Чтение локального файла (`/path/to/image.jpg`)
- Валидация формата (JPEG, PNG, WebP)
- Resize/crop до требуемых размеров
- Конвертация в PIL.Image

**Архитектура:**
```python
from pathlib import Path
from typing import Union
from PIL import Image
import requests
import base64
from io import BytesIO

class ImageLoader:
    """Utility для загрузки изображений из разных источников."""
    
    def __init__(self, max_size_mb: int = 10):
        self.max_size_mb = max_size_mb
    
    def load(self, source: str) -> Image.Image:
        """
        Загрузить изображение из URL, base64 или локального файла.
        
        Args:
            source: URL, base64 data URI, или путь к файлу
            
        Returns:
            PIL.Image объект
            
        Raises:
            ValueError: Если формат неподдерживаемый или размер превышен
            IOError: Если загрузка не удалась
        """
        if source.startswith('http://') or source.startswith('https://'):
            return self._load_from_url(source)
        elif source.startswith('data:image'):
            return self._load_from_base64(source)
        else:
            return self._load_from_file(source)
    
    def _load_from_url(self, url: str) -> Image.Image:
        """Загрузить из HTTP(S) URL."""
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Check size
        size_mb = int(response.headers.get('Content-Length', 0)) / 1024 / 1024
        if size_mb > self.max_size_mb:
            raise ValueError(f"Image too large: {size_mb:.1f}MB > {self.max_size_mb}MB")
        
        image = Image.open(BytesIO(response.content))
        return self._validate_and_convert(image)
    
    def _load_from_base64(self, data_uri: str) -> Image.Image:
        """Загрузить из base64 data URI."""
        # Parse: data:image/jpeg;base64,/9j/4AAQ...
        header, encoded = data_uri.split(',', 1)
        decoded = base64.b64decode(encoded)
        image = Image.open(BytesIO(decoded))
        return self._validate_and_convert(image)
    
    def _load_from_file(self, path: str) -> Image.Image:
        """Загрузить из локального файла."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        image = Image.open(file_path)
        return self._validate_and_convert(image)
    
    def _validate_and_convert(self, image: Image.Image) -> Image.Image:
        """Валидация и конвертация в RGB."""
        # Validate format
        if image.format not in ['JPEG', 'PNG', 'WEBP', None]:
            raise ValueError(f"Unsupported format: {image.format}")
        
        # Convert to RGB (CogVideoX требует RGB)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        
        return image
```

#### 2.2. Реализовать Image2Video Engine

**Файл:** `src/services/generation/engines/image2video.py`

**Архитектура:**
```python
from pathlib import Path
from typing import Optional
from PIL import Image

from .base import BaseVideoEngine
from src.services.generation.config import GenerationConfig
from src.services.generation.utils.image_loader import ImageLoader
from src.domain.exceptions import ModelNotLoadedError, NSFWContentError


class CogVideoImage2VideoEngine(BaseVideoEngine):
    """
    Engine для Image-to-Video генерации используя CogVideoX-5b-I2V.
    
    Features:
    - Анимирует статические изображения
    - Поддержка URL, base64, локальных файлов
    - Safety checking
    - Оптимизирован для 24GB VRAM
    """
    
    def __init__(self, config: Optional[GenerationConfig] = None):
        super().__init__(config)
        self.model_id = self.config.I2V_MODEL_ID
        self.image_loader = ImageLoader()
    
    def initialize(self) -> None:
        """Загрузить CogVideoX-5b-I2V pipeline."""
        if self._initialized:
            return
        
        self.logger.info("=" * 60)
        self.logger.info(f"Loading Image-to-Video model: {self.model_id}")
        self.logger.info("=" * 60)
        
        try:
            from diffusers import CogVideoXImageToVideoPipeline
            import torch
            
            # Load pipeline
            self.pipe = CogVideoXImageToVideoPipeline.from_pretrained(
                self.model_id,
                **self.config.get_optimization_kwargs()
            )
            
            # Apply optimizations
            self._apply_optimizations()
            
            # Load safety checker
            self._load_safety_checker()
            
            self._initialized = True
            self.logger.info("✅ Image-to-Video engine ready")
            
        except ImportError as e:
            raise ImportError(f"Missing library: {e}")
        except Exception as e:
            raise Exception(f"Failed to initialize I2V engine: {e}")
    
    def generate(
        self,
        prompt: str,
        input_image: str,  # NEW: URL, base64, or path
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """
        Сгенерировать видео из изображения.
        
        Args:
            prompt: Текстовое описание анимации
            input_image: URL, base64, или путь к изображению
            negative_prompt: Негативный промпт
            seed: Seed для воспроизводимости
            guidance_scale: Guidance scale (по умолчанию из config)
            num_inference_steps: Число шагов (по умолчанию из config)
            num_frames: Число кадров (по умолчанию из config)
            
        Returns:
            Path к сгенерированному видео
            
        Raises:
            ModelNotLoadedError: Если модель не загружена
            NSFWContentError: Если обнаружен NSFW контент
            ValueError: Если изображение не загрузилось
        """
        if not self._initialized:
            raise ModelNotLoadedError("Engine not initialized")
        
        # Use defaults if not provided
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        
        # Load input image
        try:
            image = self.image_loader.load(input_image)
            self.logger.info(f"✓ Input image loaded: {image.size}")
        except Exception as e:
            raise ValueError(f"Failed to load input image: {e}")
        
        # Create generator
        generator = self._create_generator(seed)
        
        # Generate
        self.logger.info(f"Generating video from image (prompt: '{prompt[:50]}...')")
        self.logger.info(f"  Steps: {num_inference_steps}, Frames: {num_frames}, Guidance: {guidance_scale}")
        
        output = self.pipe(
            prompt=prompt,
            image=image,  # Reference image
            negative_prompt=negative_prompt,
            num_inference_steps=num_inference_steps,
            num_frames=num_frames,
            guidance_scale=guidance_scale,
            generator=generator
        )
        
        frames = output.frames[0]
        
        # Safety check
        if not self._check_safety(frames):
            raise NSFWContentError("NSFW content detected")
        
        # Export
        video_path = self._export_video(
            frames,
            prefix="i2v",
            fps=kwargs.get('fps', self.config.DEFAULT_FPS)
        )
        
        return video_path
```

#### 2.3. Обновить Orchestrator для I2V

**Файл:** `src/services/generation/orchestrator.py`

**Изменения:**
- Добавить lazy loading для I2V engine
- Обновить `_process_single_prompt` для обработки `input_images`

```python
def _get_engine(self, mode: GenerationMode) -> BaseVideoEngine:
    """Get or create engine."""
    if mode == GenerationMode.TEXT2VIDEO:
        if not self._t2v_engine:
            self._t2v_engine = CogVideoText2VideoEngine(self.config)
        return self._t2v_engine
    
    elif mode == GenerationMode.IMAGE2VIDEO:
        if not self._i2v_engine:
            from .engines.image2video import CogVideoImage2VideoEngine
            self._i2v_engine = CogVideoImage2VideoEngine(self.config)
        return self._i2v_engine
    
    else:
        raise ValueError(f"Unknown mode: {mode}")

def _process_single_prompt(self, job: GenJob, engine: BaseVideoEngine, prompt: str, index: int):
    """Process single prompt (updated for I2V)."""
    # ...existing code...
    
    # Prepare kwargs
    kwargs = {
        'prompt': prompt,
        'negative_prompt': job.negative_prompt,
        'seed': job.seed,
        'guidance_scale': job.guidance_scale,
        'num_inference_steps': job.num_inference_steps,
        'num_frames': job.num_frames,
        'fps': job.fps
    }
    
    # Add input_image for I2V mode
    if job.mode == GenerationMode.IMAGE2VIDEO:
        if not job.input_images or index >= len(job.input_images):
            raise ValueError(f"Missing input_image for prompt {index}")
        kwargs['input_image'] = job.input_images[index]
    
    # Generate
    video_path = engine.generate(**kwargs)
    
    # ...rest of code...
```

#### 2.4. Обновить Models для валидации I2V

**Файл:** `src/services/generation/models.py`

**Изменения:**
```python
class GenJob(BaseModel):
    # ...existing fields...
    
    @field_validator('input_images')
    @classmethod
    def validate_input_images(cls, v, values):
        """Validate input_images for I2V mode."""
        mode = values.data.get('mode')
        prompts = values.data.get('prompts')
        
        if mode == GenerationMode.IMAGE2VIDEO:
            if not v:
                raise ValueError("input_images required for IMAGE2VIDEO mode")
            if len(v) != len(prompts):
                raise ValueError(
                    f"input_images length ({len(v)}) must match prompts length ({len(prompts)})"
                )
        
        return v
```

---

## Тестирование

### Unit Tests

**Структура:**
```
tests/unit/services/generation/
├── __init__.py
├── test_config.py              # Config validation
├── test_models.py              # Pydantic model validation
├── engines/
│   ├── test_base_engine.py     # Base engine utilities
│   ├── test_text2video.py      # T2V engine (mocked)
│   └── test_image2video.py     # I2V engine (mocked)
├── utils/
│   └── test_image_loader.py    # Image loader unit tests
└── test_orchestrator.py        # Orchestrator logic (mocked engines)
```

#### 1. Test Config

**Файл:** `tests/unit/services/generation/test_config.py`

```python
import pytest
from src.services.generation.config import GenerationConfig

def test_default_config():
    """Test default configuration values."""
    config = GenerationConfig()
    assert config.T2V_MODEL_ID == "THUDM/CogVideoX-5b-I2V"
    assert config.DEFAULT_GUIDANCE_SCALE == 6.0
    assert config.DEFAULT_NUM_FRAMES == 49

def test_env_override(monkeypatch):
    """Test environment variable override."""
    monkeypatch.setenv("GEN_DEFAULT_GUIDANCE_SCALE", "8.0")
    config = GenerationConfig()
    assert config.DEFAULT_GUIDANCE_SCALE == 8.0

def test_validation():
    """Test parameter validation."""
    config = GenerationConfig()
    
    # Valid
    config.validate_generation_params(6.0, 50, 49)
    
    # Invalid guidance_scale
    with pytest.raises(ValueError, match="guidance_scale"):
        config.validate_generation_params(25.0, 50, 49)
    
    # Invalid steps
    with pytest.raises(ValueError, match="num_inference_steps"):
        config.validate_generation_params(6.0, 5, 49)
```

#### 2. Test Models

**Файл:** `tests/unit/services/generation/test_models.py`

```python
import pytest
from src.services.generation.models import GenJob, GenerationMode

def test_genjob_text2video():
    """Test GenJob for T2V mode."""
    job = GenJob(prompts=["test prompt"])
    assert job.mode == GenerationMode.TEXT2VIDEO
    assert len(job.prompts) == 1
    assert job.guidance_scale == 6.0

def test_genjob_image2video():
    """Test GenJob for I2V mode."""
    job = GenJob(
        mode=GenerationMode.IMAGE2VIDEO,
        prompts=["animate this"],
        input_images=["https://example.com/image.jpg"]
    )
    assert job.mode == GenerationMode.IMAGE2VIDEO
    assert len(job.input_images) == 1

def test_genjob_i2v_validation_missing_images():
    """Test I2V validation fails without input_images."""
    with pytest.raises(ValueError, match="input_images required"):
        GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"]
        )

def test_genjob_i2v_validation_length_mismatch():
    """Test I2V validation fails on length mismatch."""
    with pytest.raises(ValueError, match="must match"):
        GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["prompt1", "prompt2"],
            input_images=["image1.jpg"]  # Length mismatch
        )
```

#### 3. Test Image Loader

**Файл:** `tests/unit/services/generation/utils/test_image_loader.py`

```python
import pytest
from unittest.mock import patch, Mock
from PIL import Image
from io import BytesIO
from src.services.generation.utils.image_loader import ImageLoader

@pytest.fixture
def loader():
    return ImageLoader()

@pytest.fixture
def sample_image():
    """Create sample RGB image."""
    img = Image.new('RGB', (512, 512), color='red')
    return img

def test_load_from_url_success(loader, sample_image):
    """Test successful URL loading."""
    with patch('requests.get') as mock_get:
        # Mock response
        buffer = BytesIO()
        sample_image.save(buffer, format='JPEG')
        buffer.seek(0)
        
        mock_response = Mock()
        mock_response.content = buffer.read()
        mock_response.headers = {'Content-Length': '1024'}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        # Load
        result = loader.load("https://example.com/image.jpg")
        assert isinstance(result, Image.Image)
        assert result.mode == 'RGB'

def test_load_from_base64(loader, sample_image):
    """Test base64 loading."""
    import base64
    
    # Create base64 data URI
    buffer = BytesIO()
    sample_image.save(buffer, format='JPEG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    data_uri = f"data:image/jpeg;base64,{encoded}"
    
    # Load
    result = loader.load(data_uri)
    assert isinstance(result, Image.Image)
    assert result.mode == 'RGB'

def test_load_from_file(loader, tmp_path, sample_image):
    """Test local file loading."""
    # Save to temp file
    file_path = tmp_path / "test.jpg"
    sample_image.save(file_path)
    
    # Load
    result = loader.load(str(file_path))
    assert isinstance(result, Image.Image)
    assert result.mode == 'RGB'

def test_load_file_not_found(loader):
    """Test file not found error."""
    with pytest.raises(FileNotFoundError):
        loader.load("/nonexistent/file.jpg")

def test_load_url_too_large(loader):
    """Test size limit enforcement."""
    with patch('requests.get') as mock_get:
        mock_response = Mock()
        mock_response.headers = {'Content-Length': str(20 * 1024 * 1024)}  # 20MB
        mock_get.return_value = mock_response
        
        with pytest.raises(ValueError, match="too large"):
            loader.load("https://example.com/huge.jpg")
```

### Integration Tests

**Структура:**
```
tests/integration/generation/
├── __init__.py
├── conftest.py                      # Fixtures
├── test_text2video_workflow.py      # T2V end-to-end
├── test_image2video_workflow.py     # I2V end-to-end
└── test_batch_processing.py         # Batch processing
```

#### 1. Fixtures

**Файл:** `tests/integration/generation/conftest.py`

```python
import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_cogvideo_pipeline():
    """Mock CogVideoX pipeline for testing."""
    with patch('diffusers.CogVideoXPipeline') as mock_cls:
        mock_pipe = MagicMock()
        
        # Mock generation
        def mock_call(*args, **kwargs):
            # Return fake frames
            import numpy as np
            frames = [np.zeros((480, 720, 3), dtype=np.uint8) for _ in range(49)]
            return MagicMock(frames=[frames])
        
        mock_pipe.__call__ = mock_call
        mock_cls.from_pretrained.return_value = mock_pipe
        
        yield mock_pipe

@pytest.fixture
def mock_cogvideo_i2v_pipeline():
    """Mock CogVideoX I2V pipeline."""
    with patch('diffusers.CogVideoXImageToVideoPipeline') as mock_cls:
        mock_pipe = MagicMock()
        
        def mock_call(*args, **kwargs):
            import numpy as np
            frames = [np.zeros((480, 720, 3), dtype=np.uint8) for _ in range(49)]
            return MagicMock(frames=[frames])
        
        mock_pipe.__call__ = mock_call
        mock_cls.from_pretrained.return_value = mock_pipe
        
        yield mock_pipe

@pytest.fixture
def mock_b2_client():
    """Mock B2 client."""
    with patch('src.infrastructure.storage.b2_client.B2Client') as mock_cls:
        mock_client = MagicMock()
        mock_client.upload.return_value = "https://b2.example.com/video.mp4"
        mock_cls.return_value = mock_client
        yield mock_client
```

#### 2. Test T2V Workflow

**Файл:** `tests/integration/generation/test_text2video_workflow.py`

```python
import pytest
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.models import GenJob, GenerationMode

def test_text2video_single_prompt(mock_cogvideo_pipeline, mock_b2_client):
    """Test T2V workflow with single prompt."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["A cat dancing"]
    )
    
    orchestrator = GenerationOrchestrator()
    result = orchestrator.process_job(job)
    
    assert result.successful == 1
    assert result.failed == 0
    assert len(result.results) == 1
    assert result.results[0].success is True
    assert result.results[0].url is not None

def test_text2video_batch(mock_cogvideo_pipeline, mock_b2_client):
    """Test T2V batch processing."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=[
            "A cat dancing",
            "A dog running",
            "A bird flying"
        ]
    )
    
    orchestrator = GenerationOrchestrator()
    result = orchestrator.process_job(job)
    
    assert result.successful == 3
    assert result.failed == 0
    assert len(result.results) == 3

def test_text2video_with_seed(mock_cogvideo_pipeline):
    """Test reproducibility with seed."""
    job = GenJob(
        prompts=["test"],
        seed=42
    )
    
    orchestrator = GenerationOrchestrator()
    result = orchestrator.process_job(job)
    
    assert result.results[0].success is True
```

#### 3. Test I2V Workflow

**Файл:** `tests/integration/generation/test_image2video_workflow.py`

```python
import pytest
from PIL import Image
from io import BytesIO
import base64
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.models import GenJob, GenerationMode

@pytest.fixture
def sample_image_base64():
    """Create sample image as base64."""
    img = Image.new('RGB', (512, 512), color='blue')
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{encoded}"

def test_image2video_single(mock_cogvideo_i2v_pipeline, sample_image_base64):
    """Test I2V with single image."""
    job = GenJob(
        mode=GenerationMode.IMAGE2VIDEO,
        prompts=["Animate this image"],
        input_images=[sample_image_base64]
    )
    
    orchestrator = GenerationOrchestrator()
    result = orchestrator.process_job(job)
    
    assert result.successful == 1
    assert result.results[0].success is True

def test_image2video_batch(mock_cogvideo_i2v_pipeline, sample_image_base64):
    """Test I2V batch processing."""
    job = GenJob(
        mode=GenerationMode.IMAGE2VIDEO,
        prompts=["animate 1", "animate 2"],
        input_images=[sample_image_base64, sample_image_base64]
    )
    
    orchestrator = GenerationOrchestrator()
    result = orchestrator.process_job(job)
    
    assert result.successful == 2
```

---

## Deployment & CI/CD

### Docker Build & Push

**Скрипт:** `scripts/build_and_push_gen.sh`

```bash
#!/bin/bash
set -e

IMAGE_NAME="your-registry/video-gen"
VERSION="1.0.0"

echo "Building Docker image..."
docker build \
  -f docker/Dockerfile.gen \
  -t ${IMAGE_NAME}:${VERSION} \
  -t ${IMAGE_NAME}:latest \
  .

echo "Pushing to registry..."
docker push ${IMAGE_NAME}:${VERSION}
docker push ${IMAGE_NAME}:latest

echo "✅ Build and push completed"
```

### Vast.ai Deployment

**Пример команды:**
```bash
docker run --rm --gpus all \
  -v /workspace/hf_cache:/root/.cache/huggingface \
  -e B2_KEY="${B2_KEY}" \
  -e B2_SECRET="${B2_SECRET}" \
  -e B2_BUCKET="${B2_BUCKET}" \
  -e GEN_DEFAULT_NUM_INFERENCE_STEPS=50 \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "mode": "text2video",
    "prompts": ["A cyberpunk city at night", "A sunset over mountains"],
    "guidance_scale": 7.0,
    "num_frames": 49
  }'
```

---

## Метрики и мониторинг

### Логи

**Структура:**
```json
{
  "timestamp": "2026-02-02T10:30:00Z",
  "level": "INFO",
  "job_id": "abc123",
  "mode": "text2video",
  "prompt_index": 0,
  "stage": "generation",
  "metrics": {
    "inference_time_seconds": 45.3,
    "num_frames": 49,
    "file_size_mb": 12.5
  }
}
```

### Ключевые метрики

- **Generation Time**: Время генерации одного видео
- **Throughput**: Видео в час
- **Success Rate**: % успешных генераций
- **VRAM Usage**: Пик использования VRAM
- **Upload Time**: Время загрузки в B2

---

## Следующие шаги (Phase 3+)

1. **Adaptive Batching**: Динамическая подстройка batch size на основе доступной VRAM
2. **Multi-GPU Support**: Распределение промптов по нескольким GPU
3. **Video Post-Processing**: Upscaling, stabilization, color grading
4. **Advanced Safety Checking**: Frame-by-frame NSFW detection
5. **Metrics Dashboard**: Grafana + Prometheus для мониторинга
6. **Queue System**: Redis/RabbitMQ для обработки очереди jobs

---

## Архитектурные преимущества

### ✅ Extensibility (Расширяемость)
- Новые engines добавляются без изменения orchestrator
- Новые storage backends реализуют `StorageProtocol`

### ✅ Maintainability (Поддерживаемость)
- Четкое разделение ответственности (SRP)
- Dependency Injection для тестирования
- Типизация и валидация через Pydantic

### ✅ Performance (Производительность)
- Встроенная модель (offline mode) → быстрый старт
- Lazy loading engines → экономия VRAM
- Batch processing → эффективная утилизация GPU

### ✅ Resilience (Устойчивость)
- Fail-safe batch processing
- Graceful degradation (без B2 можно работать)
- Retry механизмы в B2Client

---

## Заключение

Данный план обеспечивает:

1. **Фаза 1 (T2V)**: Минимально жизнеспособный продукт с полной функциональностью
2. **Фаза 2 (I2V)**: Расширение на Image-to-Video без переписывания архитектуры
3. **Тестирование**: 100% покрытие критичных компонентов
4. **Deployment**: Готовое решение для Vast.ai с встроенной моделью

**Архитектура соответствует:**
- ✅ Clean Architecture
- ✅ SOLID принципам
- ✅ KISS, YAGNI, DRY
- ✅ Fail-Safe Design

**Все готово к реализации!** 🚀
