# План реализации модуля Text-to-Video и Image-to-Video генерации

## Обзор

Данный документ описывает пошаговый план реализации модуля генерации видео с поддержкой двух режимов:
1. **Text-to-Video (T2V)** - генерация видео из текстового описания
2. **Image-to-Video (I2V)** - генерация видео из статичного изображения + текстовое описание

## Текущее состояние

### ✅ Уже реализовано в проекте
- Инфраструктура загрузки в B2/S3/R2 (`src/infrastructure/storage/b2_client.py`)
- Система логирования (`src/shared/logging.py`)
- Domain layer с протоколами и исключениями (`src/domain/`)
- Система тестирования (`tests/`)
- Docker инфраструктура

### ❌ Требуется реализовать
- Модуль генерации видео (`src/services/generation/`)
- Движки T2V и I2V
- Оркестратор с поддержкой обоих режимов
- CLI entrypoint для worker'а
- Docker образ для генерации
- Комплект тестов

---

## ЭТАП 1: Text-to-Video (Приоритет: ВЫСОКИЙ)

### 1.1 Domain Layer - Протоколы и модели

**Файлы:**
- `src/domain/generation.py` (новый)

**Задачи:**
1. Создать протокол `IVideoGenerator`:
   ```python
   class IVideoGenerator(Protocol):
       def generate(self, prompt: str, **kwargs) -> Path
       def initialize() -> None
       def cleanup() -> None
   ```

2. Создать domain модели:
   - `GenerationMode` (Enum: TEXT2VIDEO, IMAGE2VIDEO)
   - `VideoGenerationRequest` (базовый dataclass)
   - `GenerationMetadata` (результат генерации)

3. Добавить domain исключения:
   - `GenerationError`
   - `ModelNotLoadedError`
   - `NSFWContentError`

**Тесты:**
- `tests/unit/domain/test_generation_protocols.py`
- `tests/unit/domain/test_generation_models.py`

---

### 1.2 Configuration Layer

**Файлы:**
- `src/services/generation/config.py` (новый)

**Задачи:**
1. Создать `GenerationConfig` на базе `pydantic_settings.BaseSettings`:
   ```python
   class GenerationConfig(BaseSettings):
       # Model settings
       T2V_MODEL_ID: str = "THUDM/CogVideoX-5b"
       I2V_MODEL_ID: str = "THUDM/CogVideoX-5b-I2V"
       
       # Generation defaults
       DEFAULT_GUIDANCE_SCALE: float = 6.0
       DEFAULT_NUM_INFERENCE_STEPS: int = 50
       DEFAULT_NUM_FRAMES: int = 49
       DEFAULT_FPS: int = 8
       
       # Performance
       USE_BFLOAT16: bool = True
       ENABLE_CPU_OFFLOAD: bool = True
       ENABLE_VAE_SLICING: bool = True
       ENABLE_TILING: bool = True
       USE_XFORMERS: bool = True
       
       # Safety
       ENABLE_SAFETY_CHECKER: bool = True
       SAFETY_CHECKER_MODEL: str = "CompVis/stable-diffusion-safety-checker"
       
       # Paths
       HF_CACHE_DIR: str = "/root/.cache/huggingface"
       TEMP_DIR: str = "/tmp/generation"
       
       class Config:
           env_prefix = "GEN_"
   ```

2. Добавить методы:
   - `get_torch_dtype()` - возвращает torch dtype
   - `get_optimization_kwargs()` - kwargs для pipeline
   - `temp_dir_path` property
   - `hf_cache_path` property

**Тесты:**
- `tests/unit/services/generation/test_config.py`
  - Загрузка из environment
  - Валидация значений
  - Default values

---

### 1.3 Data Models Layer

**Файлы:**
- `src/services/generation/models.py` (новый)

**Задачи:**
1. Создать Pydantic модели для API:

```python
class GenerationMode(str, Enum):
    TEXT2VIDEO = "text2video"
    IMAGE2VIDEO = "image2video"

class GenJob(BaseModel):
    """Спецификация задачи генерации"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: GenerationMode = Field(default=GenerationMode.TEXT2VIDEO)
    
    # Text-to-Video fields
    prompts: List[str] = Field(..., min_items=1, max_items=100)
    negative_prompt: Optional[str] = None
    
    # Image-to-Video fields (опционально для I2V)
    input_images: Optional[List[str]] = None  # URLs или base64
    
    # Generation parameters
    seed: Optional[int] = None
    guidance_scale: float = Field(6.0, ge=1.0, le=20.0)
    num_inference_steps: int = Field(50, ge=10, le=200)
    num_frames: int = Field(49, ge=1, le=96)
    fps: int = Field(8, ge=1, le=30)
    
    # Output
    output_prefix: str = "generated/"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('input_images')
    def validate_input_images(cls, v, values):
        mode = values.get('mode')
        if mode == GenerationMode.IMAGE2VIDEO:
            if not v:
                raise ValueError("input_images required for image2video mode")
            if len(v) != len(values.get('prompts', [])):
                raise ValueError("input_images count must match prompts count")
        return v
    
    def get_output_key(self, index: int) -> str:
        """Генерация ключа для S3"""
        pass

class GenerationResult(BaseModel):
    """Результат одной генерации"""
    job_id: str
    prompt_index: int
    prompt: str
    mode: GenerationMode
    
    # Output
    output_key: str
    url: Optional[str] = None
    local_path: Optional[Path] = None
    
    # Metadata
    size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    num_frames: Optional[int] = None
    
    # Status
    success: bool = True
    error: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)

class BatchGenerationResult(BaseModel):
    """Результат батча"""
    job_id: str
    mode: GenerationMode
    total_prompts: int
    successful: int = 0
    failed: int = 0
    results: List[GenerationResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
```

2. Добавить методы:
   - `GenJob.from_json(json_str)` - парсинг из JSON
   - `GenJob.to_json()` - сериализация
   - `GenJob.validate()` - бизнес-валидация

**Тесты:**
- `tests/unit/services/generation/test_models.py`
  - Валидация T2V джоб
  - Валидация I2V джоб
  - JSON сериализация/десериализация
  - Граничные случаи (пустые промпты, превышение лимитов)

---

### 1.4 Engine Layer - CogVideoX Text-to-Video

**Файлы:**
- `src/services/generation/engines/__init__.py` (новый)
- `src/services/generation/engines/base.py` (новый)
- `src/services/generation/engines/text2video.py` (новый)

**Задачи:**

#### 1.4.1 Base Engine
```python
# base.py
from abc import ABC, abstractmethod

class BaseVideoEngine(ABC):
    """Базовый класс для всех движков генерации"""
    
    def __init__(self, config: GenerationConfig):
        self.config = config
        self.logger = get_logger(__name__)
        self._initialized = False
        self.pipe = None
        self.safety_checker = None
    
    @abstractmethod
    def initialize(self) -> None:
        """Загрузка модели"""
        pass
    
    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> Path:
        """Генерация видео"""
        pass
    
    def _check_safety(self, frames: List) -> bool:
        """Проверка NSFW контента"""
        pass
    
    def _create_generator(self, seed: Optional[int]) -> Optional[torch.Generator]:
        """Создание генератора с seed"""
        pass
    
    def cleanup(self) -> None:
        """Освобождение ресурсов"""
        pass
```

#### 1.4.2 Text-to-Video Engine
```python
# text2video.py
from diffusers import CogVideoXPipeline

class CogVideoText2VideoEngine(BaseVideoEngine):
    """Движок для Text-to-Video генерации"""
    
    def initialize(self) -> None:
        """Загрузка CogVideoX-5b модели"""
        self.logger.info(f"Loading T2V model: {self.config.T2V_MODEL_ID}")
        
        # Load pipeline
        self.pipe = CogVideoXPipeline.from_pretrained(
            self.config.T2V_MODEL_ID,
            torch_dtype=self.config.get_torch_dtype(),
            cache_dir=str(self.config.hf_cache_path)
        )
        
        # Apply optimizations
        if self.config.ENABLE_CPU_OFFLOAD:
            self.pipe.enable_model_cpu_offload()
        
        if self.config.ENABLE_VAE_SLICING:
            self.pipe.enable_vae_slicing()
        
        if self.config.ENABLE_TILING:
            self.pipe.enable_tiling()
        
        if self.config.USE_XFORMERS:
            try:
                self.pipe.enable_xformers_memory_efficient_attention()
            except ImportError:
                self.logger.warning("xformers not available")
        
        # Load safety checker
        if self.config.ENABLE_SAFETY_CHECKER:
            from transformers import pipeline as transformers_pipeline
            self.safety_checker = transformers_pipeline(
                "image-classification",
                model=self.config.SAFETY_CHECKER_MODEL,
                device="cuda" if torch.cuda.is_available() else "cpu"
            )
        
        self._initialized = True
        self.logger.info("T2V engine initialized")
    
    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """Генерация видео из текста"""
        if not self._initialized:
            self.initialize()
        
        # Defaults from config
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        
        self.logger.info(f"Generating T2V: '{prompt[:50]}...'")
        
        # Generate
        with torch.inference_mode():
            output = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_videos_per_prompt=1,
                num_inference_steps=num_inference_steps,
                num_frames=num_frames,
                guidance_scale=guidance_scale,
                generator=self._create_generator(seed),
                **kwargs
            )
        
        frames = output.frames[0]
        
        # Safety check
        if self.config.ENABLE_SAFETY_CHECKER:
            if not self._check_safety(frames):
                raise NSFWContentError("NSFW content detected")
        
        # Export to file
        output_path = self._export_video(frames)
        return output_path
    
    def _export_video(self, frames: List) -> Path:
        """Экспорт фреймов в видео файл"""
        from diffusers.utils import export_to_video
        
        temp_dir = self.config.temp_dir_path
        output_path = temp_dir / f"t2v_{uuid.uuid4().hex[:8]}.mp4"
        
        export_to_video(
            frames,
            str(output_path),
            fps=self.config.DEFAULT_FPS
        )
        
        self.logger.info(f"Video exported: {output_path} ({output_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return output_path
```

**Тесты:**
- `tests/unit/services/generation/engines/test_base_engine.py`
  - Инициализация базового движка
  - Safety checker
  - Generator creation
  
- `tests/unit/services/generation/engines/test_text2video_engine.py`
  - Загрузка модели (mock)
  - Генерация видео (mock)
  - Обработка ошибок
  - Safety check

- `tests/integration/generation/test_text2video_real.py` (требует GPU)
  - Реальная генерация на GPU
  - Проверка output файла

---

### 1.5 Orchestrator Layer

**Файлы:**
- `src/services/generation/orchestrator.py` (новый)

**Задачи:**
1. Создать `GenerationOrchestrator`:

```python
class GenerationOrchestrator:
    """Оркестратор workflow генерации"""
    
    def __init__(
        self,
        config: Optional[GenerationConfig] = None,
        b2_client: Optional[B2Client] = None
    ):
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        # Engines (lazy loading)
        self._t2v_engine: Optional[CogVideoText2VideoEngine] = None
        self._i2v_engine: Optional[CogVideoImage2VideoEngine] = None
        
        # B2 client
        self.b2_client = b2_client
        if not self.b2_client:
            try:
                self.b2_client = B2Client()
            except Exception as e:
                self.logger.warning(f"B2 client unavailable: {e}")
        
        # State
        self._current_job: Optional[GenJob] = None
        self._results: List[GenerationResult] = []
    
    def process_job(self, job: GenJob) -> BatchGenerationResult:
        """Обработка задачи генерации"""
        self._current_job = job
        self._results = []
        
        batch_result = BatchGenerationResult(
            job_id=job.id,
            mode=job.mode,
            total_prompts=len(job.prompts)
        )
        
        try:
            # Select engine
            engine = self._get_engine(job.mode)
            engine.initialize()
            
            # Process prompts
            for i, prompt in enumerate(job.prompts):
                result = self._process_single_prompt(job, engine, prompt, i)
                self._results.append(result)
                
                if result.success:
                    batch_result.successful += 1
                else:
                    batch_result.failed += 1
                
                batch_result.results.append(result)
            
            batch_result.completed_at = datetime.utcnow()
            
            self.logger.info(
                f"Job {job.id} completed: {batch_result.successful}/{batch_result.total_prompts} successful"
            )
            
            return batch_result
            
        except Exception as e:
            self.logger.error(f"Job {job.id} failed: {e}")
            batch_result.completed_at = datetime.utcnow()
            return batch_result
        
        finally:
            self._cleanup_temporary_files()
    
    def _get_engine(self, mode: GenerationMode) -> BaseVideoEngine:
        """Получение движка по режиму"""
        if mode == GenerationMode.TEXT2VIDEO:
            if not self._t2v_engine:
                self._t2v_engine = CogVideoText2VideoEngine(self.config)
            return self._t2v_engine
        
        elif mode == GenerationMode.IMAGE2VIDEO:
            if not self._i2v_engine:
                self._i2v_engine = CogVideoImage2VideoEngine(self.config)
            return self._i2v_engine
        
        else:
            raise ValueError(f"Unknown mode: {mode}")
    
    def _process_single_prompt(
        self,
        job: GenJob,
        engine: BaseVideoEngine,
        prompt: str,
        index: int
    ) -> GenerationResult:
        """Обработка одного промпта"""
        result = GenerationResult(
            job_id=job.id,
            prompt_index=index,
            prompt=prompt,
            mode=job.mode,
            output_key=job.get_output_key(index)
        )
        
        try:
            # Generate video
            self.logger.info(f"[{index + 1}/{len(job.prompts)}] Generating: '{prompt[:50]}...'")
            
            video_path = engine.generate(
                prompt=prompt,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                guidance_scale=job.guidance_scale,
                num_inference_steps=job.num_inference_steps,
                num_frames=job.num_frames
            )
            
            result.local_path = video_path
            result.size_bytes = video_path.stat().st_size
            
            # Upload to B2
            if self.b2_client:
                self.logger.info(f"Uploading to B2: {result.output_key}")
                self.b2_client.upload_file(video_path, result.output_key)
                result.url = self.b2_client.get_presigned_url(result.output_key)
            else:
                result.url = f"file://{video_path}"
            
            # Cleanup local file
            video_path.unlink(missing_ok=True)
            
            self.logger.info(f"[{index + 1}] Success: {result.url}")
            
        except Exception as e:
            self.logger.error(f"[{index + 1}] Failed: {e}")
            result.success = False
            result.error = str(e)
        
        return result
    
    def _cleanup_temporary_files(self) -> None:
        """Очистка временных файлов"""
        temp_dir = self.config.temp_dir_path
        if temp_dir.exists():
            import time
            current_time = time.time()
            for file_path in temp_dir.glob("*"):
                if file_path.is_file():
                    age = current_time - file_path.stat().st_mtime
                    if age > 3600:  # 1 hour
                        file_path.unlink()
```

**Тесты:**
- `tests/unit/services/generation/test_orchestrator.py`
  - Engine selection по mode
  - Обработка single prompt (mock)
  - Обработка batch (mock)
  - Upload to B2 (mock)
  - Error handling
  - Cleanup

---

### 1.6 CLI Entrypoint

**Файлы:**
- `src/entrypoints/run_gen.py` (новый)

**Задачи:**
1. Создать CLI worker:

```python
#!/usr/bin/env python3
"""
Entry point for video generation worker.

Run & die pattern: parse job -> generate -> upload -> exit
"""

import argparse
import json
import sys
from pathlib import Path

from src.services.generation.models import GenJob
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig
from src.shared.logging import setup_logger, get_logger


def parse_arguments():
    parser = argparse.ArgumentParser(description="Video Generation Worker")
    parser.add_argument(
        '--job',
        type=str,
        required=True,
        help='JSON job specification'
    )
    parser.add_argument(
        '--config',
        type=Path,
        help='Config file path (optional)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate job without execution'
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logger("generation", level=log_level)
    logger = get_logger(__name__)
    
    logger.info("=" * 60)
    logger.info("Video Generation Worker")
    logger.info("=" * 60)
    
    try:
        # Parse job
        logger.info("Parsing job specification...")
        job = GenJob.from_json(args.job)
        logger.info(f"Job ID: {job.id}")
        logger.info(f"Mode: {job.mode}")
        logger.info(f"Prompts: {len(job.prompts)}")
        
        if args.dry_run:
            logger.info("Dry run mode - validation only")
            output = {
                "success": True,
                "message": "Job validated successfully",
                "job_id": job.id
            }
            print(json.dumps(output, indent=2))
            return 0
        
        # Load config
        config = GenerationConfig()
        logger.info(f"T2V Model: {config.T2V_MODEL_ID}")
        logger.info(f"I2V Model: {config.I2V_MODEL_ID}")
        
        # Initialize orchestrator
        orchestrator = GenerationOrchestrator(config=config)
        
        # Process job
        logger.info("Starting generation...")
        result = orchestrator.process_job(job)
        
        # Output results as JSON
        output = {
            "success": result.successful > 0,
            "job_id": result.job_id,
            "mode": result.mode,
            "total_prompts": result.total_prompts,
            "successful": result.successful,
            "failed": result.failed,
            "duration_seconds": result.duration_seconds,
            "results": [r.dict() for r in result.results]
        }
        
        print(json.dumps(output, indent=2, default=str))
        
        # Exit code: 0 if any success, 1 if all failed
        exit_code = 0 if result.successful > 0 else 1
        logger.info(f"Exiting with code: {exit_code}")
        return exit_code
        
    except Exception as e:
        logger.exception(f"Worker failed: {e}")
        output = {
            "success": False,
            "error": str(e)
        }
        print(json.dumps(output, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

**Тесты:**
- `tests/integration/entrypoints/test_run_gen.py`
  - CLI parsing
  - Dry run mode
  - Real execution (mock GPU)

---

### 1.7 Docker Image

**Файлы:**
- `Dockerfile.gen` (новый)
- `requirements.gen.txt` (новый)

**Задачи:**

#### 1.7.1 Requirements
```txt
# requirements.gen.txt
# Core ML
torch>=2.2.0
torchvision>=0.17.0
torchaudio>=2.2.0

# Diffusers
diffusers>=0.30.0
transformers>=4.40.0
accelerate>=0.30.0
safetensors>=0.4.0
xformers>=0.0.24

# Video
imageio[ffmpeg]>=2.34.0
imageio-ffmpeg>=0.5.0

# Storage
boto3>=1.34.0

# Config & Models
pydantic>=2.0.0
pydantic-settings>=2.0.0

# Utilities
numpy>=1.24.0
pillow>=10.0.0
```

#### 1.7.2 Dockerfile
```dockerfile
# Dockerfile.gen
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

LABEL maintainer="vastai_inerup"
LABEL description="Text-to-Video and Image-to-Video generation worker"

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
WORKDIR /tmp
COPY requirements.gen.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.gen.txt

# Application
WORKDIR /app
COPY src/ /app/src/

# Directories
RUN mkdir -p \
    /tmp/generation \
    /root/.cache/huggingface \
    /app/output

# Environment
ENV PYTHONPATH="/app:$PYTHONPATH"
ENV PYTHONUNBUFFERED="1"
ENV HF_HOME="/root/.cache/huggingface"
ENV TEMP_DIR="/tmp/generation"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import torch; assert torch.cuda.is_available()" || exit 1

# Default command
CMD ["python", "-m", "src.entrypoints.run_gen", "--help"]
```

**Тесты:**
- `tests/docker/test_generation_image.sh` (shell script)
  - Build image
  - Run health check
  - Test import

---

### 1.8 Интеграционные тесты

**Файлы:**
- `tests/integration/generation/test_text2video_workflow.py` (новый)

**Задачи:**
1. End-to-end тест T2V workflow:

```python
import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from src.services.generation.models import GenJob, GenerationMode
from src.services.generation.orchestrator import GenerationOrchestrator


@pytest.mark.integration
def test_text2video_workflow_mock():
    """E2E тест T2V с моками"""
    
    # Prepare job
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["A dancing cat", "A sunset"],
        guidance_scale=6.0,
        num_inference_steps=10  # Low for testing
    )
    
    # Mock B2 client
    mock_b2 = Mock()
    mock_b2.upload_file = Mock()
    mock_b2.get_presigned_url = Mock(return_value="https://fake.url/video.mp4")
    
    # Mock engine
    with patch('src.services.generation.engines.text2video.CogVideoXPipeline'):
        orchestrator = GenerationOrchestrator(b2_client=mock_b2)
        
        # Process
        result = orchestrator.process_job(job)
        
        # Assertions
        assert result.job_id == job.id
        assert result.total_prompts == 2
        assert result.mode == GenerationMode.TEXT2VIDEO


@pytest.mark.gpu
@pytest.mark.slow
def test_text2video_real_generation():
    """Реальная генерация (требует GPU)"""
    
    pytest.importorskip("torch")
    import torch
    if not torch.cuda.is_available():
        pytest.skip("GPU not available")
    
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["A simple test scene"],
        num_inference_steps=10,  # Fast test
        num_frames=9  # Short video
    )
    
    orchestrator = GenerationOrchestrator(b2_client=None)  # No upload
    result = orchestrator.process_job(job)
    
    assert result.successful == 1
    assert result.results[0].success
    assert result.results[0].local_path.exists()
```

---

## ЭТАП 2: Image-to-Video (Приоритет: СРЕДНИЙ)

### 2.1 Image-to-Video Engine

**Файлы:**
- `src/services/generation/engines/image2video.py` (новый)
- `src/services/generation/utils/image_loader.py` (новый)

**Задачи:**

#### 2.1.1 Image Loader Utility
```python
# utils/image_loader.py
from PIL import Image
import requests
import base64
from io import BytesIO

class ImageLoader:
    """Загрузка изображений из URL или base64"""
    
    @staticmethod
    def load_from_url(url: str) -> Image.Image:
        """Загрузка из URL"""
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    
    @staticmethod
    def load_from_base64(b64_str: str) -> Image.Image:
        """Загрузка из base64"""
        if b64_str.startswith('data:'):
            b64_str = b64_str.split(',', 1)[1]
        image_data = base64.b64decode(b64_str)
        return Image.open(BytesIO(image_data))
    
    @staticmethod
    def load_from_path(path: Path) -> Image.Image:
        """Загрузка из файла"""
        return Image.open(path)
    
    @classmethod
    def load(cls, source: str) -> Image.Image:
        """Автоопределение типа и загрузка"""
        if source.startswith('http://') or source.startswith('https://'):
            return cls.load_from_url(source)
        elif source.startswith('data:'):
            return cls.load_from_base64(source)
        elif Path(source).exists():
            return cls.load_from_path(Path(source))
        else:
            # Assume base64
            return cls.load_from_base64(source)
```

#### 2.1.2 I2V Engine
```python
# engines/image2video.py
from diffusers import CogVideoXImageToVideoPipeline

class CogVideoImage2VideoEngine(BaseVideoEngine):
    """Движок для Image-to-Video генерации"""
    
    def initialize(self) -> None:
        """Загрузка CogVideoX-5b-I2V модели"""
        self.logger.info(f"Loading I2V model: {self.config.I2V_MODEL_ID}")
        
        self.pipe = CogVideoXImageToVideoPipeline.from_pretrained(
            self.config.I2V_MODEL_ID,
            torch_dtype=self.config.get_torch_dtype(),
            cache_dir=str(self.config.hf_cache_path)
        )
        
        # Apply optimizations (same as T2V)
        self._apply_optimizations()
        
        # Load safety checker
        if self.config.ENABLE_SAFETY_CHECKER:
            self._load_safety_checker()
        
        self._initialized = True
        self.logger.info("I2V engine initialized")
    
    def generate(
        self,
        prompt: str,
        input_image: Union[str, Image.Image],
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """Генерация видео из изображения"""
        if not self._initialized:
            self.initialize()
        
        # Load image
        if isinstance(input_image, str):
            from src.services.generation.utils.image_loader import ImageLoader
            image = ImageLoader.load(input_image)
        else:
            image = input_image
        
        # Resize to model requirements
        image = self._preprocess_image(image)
        
        # Defaults
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        
        self.logger.info(f"Generating I2V: '{prompt[:50]}...'")
        
        # Generate
        with torch.inference_mode():
            output = self.pipe(
                prompt=prompt,
                image=image,
                negative_prompt=negative_prompt,
                num_videos_per_prompt=1,
                num_inference_steps=num_inference_steps,
                num_frames=num_frames,
                guidance_scale=guidance_scale,
                generator=self._create_generator(seed),
                **kwargs
            )
        
        frames = output.frames[0]
        
        # Safety check
        if self.config.ENABLE_SAFETY_CHECKER:
            if not self._check_safety(frames):
                raise NSFWContentError("NSFW content detected")
        
        # Export
        output_path = self._export_video(frames, prefix="i2v")
        return output_path
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Подготовка изображения под требования модели"""
        # CogVideoX требует определенные размеры (обычно 720x480 или кратные)
        target_size = (720, 480)
        
        # Resize maintaining aspect ratio
        image.thumbnail(target_size, Image.Resampling.LANCZOS)
        
        # Pad to exact size if needed
        if image.size != target_size:
            padded = Image.new('RGB', target_size, (0, 0, 0))
            offset = ((target_size[0] - image.size[0]) // 2,
                     (target_size[1] - image.size[1]) // 2)
            padded.paste(image, offset)
            return padded
        
        return image
```

**Тесты:**
- `tests/unit/services/generation/utils/test_image_loader.py`
  - Load from URL (mock requests)
  - Load from base64
  - Load from file
  - Auto detection

- `tests/unit/services/generation/engines/test_image2video_engine.py`
  - Инициализация
  - Image preprocessing
  - Генерация (mock)

- `tests/integration/generation/test_image2video_workflow.py`
  - E2E с моками
  - Real generation (GPU required)

---

### 2.2 Orchestrator Update

**Задачи:**
1. Обновить `_process_single_prompt` для поддержки I2V:

```python
def _process_single_prompt(
    self,
    job: GenJob,
    engine: BaseVideoEngine,
    prompt: str,
    index: int
) -> GenerationResult:
    """Обработка одного промпта (T2V или I2V)"""
    
    # ... existing code ...
    
    try:
        # Generate based on mode
        if job.mode == GenerationMode.TEXT2VIDEO:
            video_path = engine.generate(
                prompt=prompt,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                guidance_scale=job.guidance_scale,
                num_inference_steps=job.num_inference_steps,
                num_frames=job.num_frames
            )
        
        elif job.mode == GenerationMode.IMAGE2VIDEO:
            input_image = job.input_images[index]
            video_path = engine.generate(
                prompt=prompt,
                input_image=input_image,
                negative_prompt=job.negative_prompt,
                seed=job.seed,
                guidance_scale=job.guidance_scale,
                num_inference_steps=job.num_inference_steps,
                num_frames=job.num_frames
            )
        
        # ... rest of code ...
```

**Тесты:**
- `tests/unit/services/generation/test_orchestrator_i2v.py`
  - I2V mode selection
  - Image passing to engine

---

## ЭТАП 3: Документация и примеры

### 3.1 Обновить README_GENERATION.md

**Задачи:**
1. Добавить секцию про Image-to-Video
2. Примеры JSON для I2V mode
3. Обновить архитектурную диаграмму

### 3.2 Создать примеры использования

**Файлы:**
- `examples/generation/text2video_example.py` (новый)
- `examples/generation/image2video_example.py` (новый)
- `examples/generation/batch_example.py` (новый)

---

## ЭТАП 4: Оптимизации и Production-ready

### 4.1 Performance Optimizations

**Задачи:**
1. Добавить model warmup в engine initialization
2. Реализовать engine pool для переиспользования
3. Добавить async upload в B2 (не блокирующий генерацию)
4. Реализовать batch inference (генерация нескольких видео одновременно)

**Файлы:**
- `src/services/generation/pool.py` (новый)
- `src/services/generation/async_uploader.py` (новый)

### 4.2 Monitoring & Observability

**Задачи:**
1. Добавить метрики:
   - Generation duration
   - VRAM usage
   - Queue size
   - Success/failure rate

**Файлы:**
- `src/services/generation/metrics.py` (новый)

### 4.3 Error Recovery

**Задачи:**
1. State persistence для resume after crash
2. Retry logic с exponential backoff
3. Graceful shutdown handling

---

## Структура тестов

```
tests/
├── unit/
│   ├── domain/
│   │   ├── test_generation_protocols.py
│   │   └── test_generation_models.py
│   └── services/
│       └── generation/
│           ├── test_config.py
│           ├── test_models.py
│           ├── test_orchestrator.py
│           ├── test_orchestrator_i2v.py
│           ├── engines/
│           │   ├── test_base_engine.py
│           │   ├── test_text2video_engine.py
│           │   └── test_image2video_engine.py
│           └── utils/
│               └── test_image_loader.py
│
├── integration/
│   ├── generation/
│   │   ├── test_text2video_workflow.py
│   │   └── test_image2video_workflow.py
│   └── entrypoints/
│       └── test_run_gen.py
│
└── docker/
    └── test_generation_image.sh
```

## Приоритеты реализации

### Фаза 1: Основа (1-2 недели)
1. ✅ Domain layer (protocols, models, exceptions)
2. ✅ Configuration
3. ✅ Data models (GenJob, Results)
4. ✅ Base engine class
5. ✅ Text-to-Video engine
6. ✅ Basic orchestrator (T2V only)
7. ✅ CLI entrypoint
8. ✅ Docker image
9. ✅ Unit tests

### Фаза 2: Image-to-Video (1 неделя)
1. ✅ Image loader utility
2. ✅ Image-to-Video engine
3. ✅ Orchestrator update для I2V
4. ✅ Integration tests
5. ✅ Documentation update

### Фаза 3: Production готовность (1 неделя)
1. ✅ Performance optimizations
2. ✅ Monitoring & metrics
3. ✅ Error recovery
4. ✅ Load testing
5. ✅ Documentation & examples

---

## Зависимости между компонентами

```
Domain Layer (protocols, models)
    ↓
Configuration Layer
    ↓
Engine Layer (base → t2v, i2v)
    ↓
Orchestrator Layer
    ↓
CLI Entrypoint
    ↓
Docker Image
```

## Команды для разработки

```bash
# Создание структуры
mkdir -p src/domain/
mkdir -p src/services/generation/engines
mkdir -p src/services/generation/utils
mkdir -p src/entrypoints
mkdir -p tests/unit/domain
mkdir -p tests/unit/services/generation/engines
mkdir -p tests/integration/generation
mkdir -p tests/docker
mkdir -p examples/generation

# Запуск unit тестов
pytest tests/unit/services/generation/ -v

# Запуск integration тестов (без GPU)
pytest tests/integration/generation/ -v -m "not gpu"

# Запуск GPU тестов
pytest tests/integration/generation/ -v -m gpu

# Build Docker
docker build -f Dockerfile.gen -t video-gen:dev .

# Test Docker
docker run --rm --gpus all video-gen:dev python -m src.entrypoints.run_gen \
  --job '{"mode": "text2video", "prompts": ["test"]}' \
  --dry-run
```

---

## Контрольные точки (Checkpoints)

### Checkpoint 1: T2V MVP
- [ ] Domain layer готов
- [ ] Config + Models работают
- [ ] T2V engine генерирует видео
- [ ] Orchestrator обрабатывает T2V jobs
- [ ] CLI запускается
- [ ] Docker собирается
- [ ] Unit tests проходят

### Checkpoint 2: I2V Support
- [ ] Image loader работает
- [ ] I2V engine генерирует видео
- [ ] Orchestrator поддерживает оба режима
- [ ] Integration tests проходят

### Checkpoint 3: Production Ready
- [ ] Performance оптимизации применены
- [ ] Monitoring добавлен
- [ ] Error recovery работает
- [ ] Документация полная
- [ ] Load tests пройдены

---

## Риски и митигация

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| OOM на 24GB GPU | Высокая | CPU offload, VAE slicing, dynamic batching |
| Медленная генерация | Средняя | xformers, bfloat16, torch.compile |
| NSFW content | Средняя | Safety checker, confidence threshold tuning |
| B2 upload failures | Низкая | Retry logic, fallback to local storage |
| Model download issues | Средняя | Volume mount для cache, model preloading в Docker |

---

## Следующие шаги

После завершения базовой реализации:
1. **Мультимодальность**: Video-to-Video editing
2. **Расширенные параметры**: LoRA support, ControlNet integration
3. **Масштабирование**: Multi-GPU support, distributed inference
4. **API**: REST API для управления jobs
5. **UI**: Web interface для генерации

---

## Заключение

Данный план обеспечивает структурированную реализацию модуля генерации видео с четким разделением на этапы, полным покрытием тестами и соблюдением Clean Architecture принципов. Модуль будет изолирован от основного приложения, переиспользует существующую инфраструктуру (B2, logging) и готов к deployment на Vast.ai.
