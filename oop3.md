# План рефакторинга проекта vastai_inerup_ztp на основе ООП и SOLID

## Оглавление
1. [Анализ текущего состояния](#анализ-текущего-состояния)
2. [Целевая архитектура](#целевая-архитектура)
3. [Структура проекта](#структура-проекта)
4. [Ключевые компоненты и их взаимодействие](#ключевые-компоненты-и-их-взаимодействие)
5. [Применение принципов SOLID](#применение-принципов-solid)
6. [Детальное описание компонентов](#детальное-описание-компонентов)
7. [Диаграммы взаимодействия](#диаграммы-взаимодействия)
8. [План миграции](#план-миграции)
9. [Тестирование](#тестирование)
10. [Метрики качества](#метрики-качества)

---

## Анализ текущего состояния

### Проблемы текущей архитектуры
1. **Монолитные скрипты**: `pipeline.py` содержит 900+ строк смешанной логики
2. **Tight coupling**: прямые вызовы shell-скриптов из Python
3. **Дублирование кода**: логика retry, logging, error handling повторяется
4. **Сложное тестирование**: невозможно изолированно протестировать компоненты
5. **Хрупкость**: изменение одной части ломает другие
6. **Отсутствие абстракций**: нет интерфейсов, всё завязано на конкретных реализациях
7. **Неявные зависимости**: ENV переменные и глобальные состояния
8. **Сложная отладка**: логи смешаны, трудно отследить flow

### Технический долг
- Отсутствие unit-тестов (coverage ~5%)
- Hardcoded пути и конфигурации
- Смешивание бизнес-логики и инфраструктурного кода
- Отсутствие типизации (type hints)
- Слабая обработка ошибок

---

## Целевая архитектура

### Ключевые принципы
1. **Разделение ответственности**: каждый компонент решает одну задачу
2. **Dependency Injection**: зависимости инжектятся через конструкторы
3. **Interface segregation**: маленькие, специализированные интерфейсы
4. **Testability**: все компоненты легко мокаются и тестируются
5. **Extensibility**: новые реализации добавляются без изменения существующего кода

### Архитектурные слои
```
┌─────────────────────────────────────────┐
│         Presentation Layer              │
│  (CLI, API, Container Entrypoint)       │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│       Application Layer                 │
│  (Orchestrator, Use Cases)              │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│         Domain Layer                    │
│  (Business Logic, Processors)           │
└─────────────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────┐
│      Infrastructure Layer               │
│  (IO, FFmpeg, Network, Storage)         │
└─────────────────────────────────────────┘
```

---

## Структура проекта

```
vastai_inerup_ztp/
├── src/
│   ├── __init__.py
│   │
│   ├── domain/                          # Бизнес-логика и абстракции
│   │   ├── __init__.py
│   │   ├── models.py                    # Доменные модели (Video, Frame, ProcessingJob)
│   │   ├── protocols.py                 # Интерфейсы (Protocols)
│   │   └── exceptions.py                # Доменные исключения
│   │
│   ├── application/                     # Оркестрация и use cases
│   │   ├── __init__.py
│   │   ├── orchestrator.py              # Главный оркестратор
│   │   ├── use_cases/
│   │   │   ├── __init__.py
│   │   │   ├── upscale_video.py
│   │   │   ├── interpolate_video.py
│   │   │   └── process_video.py         # Combined (both)
│   │   └── factories.py                 # Фабрики для создания компонентов
│   │
│   ├── infrastructure/                  # Реализации инфраструктуры
│   │   ├── __init__.py
│   │   │
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── loader.py                # ConfigLoader
│   │   │   └── validators.py            # Валидаторы конфигурации
│   │   │
│   │   ├── io/
│   │   │   ├── __init__.py
│   │   │   ├── downloader.py            # HTTP/S3 downloader
│   │   │   └── uploader.py              # B2/S3 uploader
│   │   │
│   │   ├── media/
│   │   │   ├── __init__.py
│   │   │   ├── ffmpeg.py                # FFmpeg wrapper
│   │   │   ├── extractor.py             # Frame extractor
│   │   │   └── assembler.py             # Video assembler
│   │   │
│   │   ├── processors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                  # BaseProcessor
│   │   │   ├── rife/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── pytorch_wrapper.py
│   │   │   │   ├── ncnn_wrapper.py
│   │   │   │   └── fallback.py
│   │   │   └── realesrgan/
│   │   │       ├── __init__.py
│   │   │       ├── pytorch_wrapper.py
│   │   │       ├── ncnn_wrapper.py
│   │   │       └── fallback.py
│   │   │
│   │   └── storage/
│   │       ├── __init__.py
│   │       ├── temp_storage.py          # Управление временными файлами
│   │       └── pending_marker.py        # Pending upload marker
│   │
│   ├── presentation/                    # Точки входа
│   │   ├── __init__.py
│   │   ├── cli.py                       # CLI интерфейс
│   │   └── container_runner.py          # Entrypoint для контейнера
│   │
│   └── shared/                          # Общие утилиты
│       ├── __init__.py
│       ├── logging.py                   # Логирование
│       ├── retry.py                     # Retry strategies
│       ├── metrics.py                   # Метрики и мониторинг
│       └── types.py                     # Общие типы
│
├── tests/
│   ├── __init__.py
│   ├── unit/
│   │   ├── test_config/
│   │   ├── test_processors/
│   │   ├── test_media/
│   │   └── test_io/
│   ├── integration/
│   │   ├── test_orchestrator.py
│   │   └── test_end_to_end.py
│   └── fixtures/
│       ├── videos/
│       └── configs/
│
├── scripts/                             # Legacy и вспомогательные скрипты
│   ├── run_realesrgan_pytorch.sh
│   ├── run_rife_pytorch.sh
│   └── container_upload.py
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   └── deployment.md
│
├── config.yaml                          # Конфигурация по умолчанию
├── requirements.txt
├── pyproject.toml                       # Poetry/setuptools config
├── pytest.ini
├── .pylintrc
└── README.md
```

---

## Ключевые компоненты и их взаимодействие

### 1. Domain Layer (Доменный слой)

#### Protocols (Интерфейсы)
```python
# src/domain/protocols.py

from typing import Protocol, List, Optional
from pathlib import Path
from .models import Video, ProcessingResult, UploadResult

class IDownloader(Protocol):
    """Интерфейс для загрузки файлов"""
    def download(self, url: str, destination: Path) -> Path:
        """Загружает файл по URL"""
        ...
    
    def supports(self, url: str) -> bool:
        """Проверяет, поддерживается ли данный URL"""
        ...

class IExtractor(Protocol):
    """Интерфейс для извлечения кадров из видео"""
    def extract_frames(self, video: Video, output_dir: Path) -> List[Path]:
        """Извлекает кадры из видео"""
        ...
    
    def get_video_info(self, video_path: Path) -> Video:
        """Получает метаинформацию о видео"""
        ...

class IProcessor(Protocol):
    """Базовый интерфейс для процессоров"""
    def process(
        self, 
        input_frames: List[Path], 
        output_dir: Path,
        **options
    ) -> ProcessingResult:
        """Обрабатывает входные кадры"""
        ...
    
    def supports_gpu(self) -> bool:
        """Проверяет наличие GPU поддержки"""
        ...

class IAssembler(Protocol):
    """Интерфейс для сборки видео из кадров"""
    def assemble(
        self, 
        frames: List[Path], 
        output_path: Path,
        fps: float,
        **options
    ) -> Path:
        """Собирает видео из кадров"""
        ...

class IUploader(Protocol):
    """Интерфейс для загрузки результатов"""
    def upload(self, file_path: Path, key: str) -> UploadResult:
        """Загружает файл в облако"""
        ...
    
    def resume_pending(self) -> List[UploadResult]:
        """Возобновляет незавершённые загрузки"""
        ...
```

#### Domain Models
```python
# src/domain/models.py

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

@dataclass(frozen=True)
class Video:
    """Представление видео файла"""
    path: Path
    fps: float
    duration: float
    width: int
    height: int
    frame_count: int
    codec: str
    
    def __post_init__(self):
        if self.fps <= 0:
            raise ValueError("FPS must be positive")

@dataclass
class ProcessingResult:
    """Результат обработки"""
    success: bool
    output_path: Optional[Path]
    frames_processed: int
    duration_seconds: float
    metrics: Dict[str, Any]
    errors: List[str]

@dataclass
class UploadResult:
    """Результат загрузки"""
    success: bool
    url: Optional[str]
    bucket: str
    key: str
    size_bytes: int
    duration_seconds: float

@dataclass
class ProcessingJob:
    """Задача обработки видео"""
    job_id: str
    input_url: str
    mode: str  # 'upscale', 'interp', 'both'
    scale: float
    target_fps: Optional[int]
    created_at: datetime
    config: Dict[str, Any]
```

#### Domain Exceptions
```python
# src/domain/exceptions.py

class DomainException(Exception):
    """Базовое исключение домена"""
    pass

class VideoProcessingError(DomainException):
    """Ошибка обработки видео"""
    pass

class DownloadError(DomainException):
    """Ошибка загрузки файла"""
    pass

class UploadError(DomainException):
    """Ошибка выгрузки файла"""
    pass

class ConfigurationError(DomainException):
    """Ошибка конфигурации"""
    pass
```

---

### 2. Application Layer (Слой приложения)

#### Orchestrator (Оркестратор)
```python
# src/application/orchestrator.py

from typing import Optional
from pathlib import Path
from ..domain.protocols import (
    IDownloader, IExtractor, IProcessor, 
    IAssembler, IUploader
)
from ..domain.models import ProcessingJob, ProcessingResult
from ..shared.logging import get_logger
from ..shared.metrics import MetricsCollector

class VideoProcessingOrchestrator:
    """
    Главный оркестратор процесса обработки видео.
    
    Принцип единственной ответственности: координирует работу компонентов,
    но не выполняет реальную обработку сам.
    """
    
    def __init__(
        self,
        downloader: IDownloader,
        extractor: IExtractor,
        upscaler: Optional[IProcessor],
        interpolator: Optional[IProcessor],
        assembler: IAssembler,
        uploader: IUploader,
        temp_storage: ITempStorage,
        metrics: MetricsCollector,
        logger: Logger
    ):
        self._downloader = downloader
        self._extractor = extractor
        self._upscaler = upscaler
        self._interpolator = interpolator
        self._assembler = assembler
        self._uploader = uploader
        self._temp_storage = temp_storage
        self._metrics = metrics
        self._logger = logger
    
    def process(self, job: ProcessingJob) -> ProcessingResult:
        """
        Выполняет обработку видео согласно заданию.
        
        Open/Closed principle: метод закрыт для изменений,
        но открыт для расширения через композицию процессоров.
        """
        self._logger.info(f"Starting job {job.job_id}")
        
        try:
            # 1. Подготовка
            work_dir = self._temp_storage.create_workspace(job.job_id)
            
            # 2. Загрузка
            input_file = self._download_input(job.input_url, work_dir)
            video_info = self._extractor.get_video_info(input_file)
            
            # 3. Извлечение кадров
            frames = self._extractor.extract_frames(video_info, work_dir / "frames")
            
            # 4. Обработка (upscale + interpolation)
            processed_frames = self._process_frames(
                frames, work_dir, job.mode, job.config
            )
            
            # 5. Сборка
            output_video = self._assembler.assemble(
                processed_frames,
                work_dir / "output.mp4",
                job.target_fps or video_info.fps
            )
            
            # 6. Загрузка результата
            upload_result = self._uploader.upload(
                output_video,
                self._generate_output_key(job)
            )
            
            # 7. Очистка
            self._temp_storage.cleanup(work_dir, keep_on_error=False)
            
            return ProcessingResult(
                success=True,
                output_path=output_video,
                upload_url=upload_result.url,
                metrics=self._metrics.get_summary()
            )
            
        except Exception as e:
            self._logger.error(f"Job {job.job_id} failed: {e}")
            self._temp_storage.cleanup(work_dir, keep_on_error=True)
            raise
    
    def _process_frames(
        self, 
        frames: List[Path], 
        work_dir: Path,
        mode: str,
        config: Dict[str, Any]
    ) -> List[Path]:
        """Обрабатывает кадры согласно режиму"""
        
        if mode == "upscale":
            return self._upscaler.process(frames, work_dir / "upscaled")
        
        elif mode == "interp":
            return self._interpolator.process(frames, work_dir / "interpolated")
        
        elif mode == "both":
            # Strategy pattern: выбор порядка операций
            if config.get("strategy") == "interp-then-upscale":
                interpolated = self._interpolator.process(
                    frames, work_dir / "interpolated"
                )
                return self._upscaler.process(
                    interpolated, work_dir / "upscaled"
                )
            else:  # upscale-then-interp
                upscaled = self._upscaler.process(frames, work_dir / "upscaled")
                return self._interpolator.process(
                    upscaled, work_dir / "interpolated"
                )
        
        raise ValueError(f"Unknown mode: {mode}")
```

#### Factory Pattern
```python
# src/application/factories.py

from typing import Dict, Type
from ..domain.protocols import IProcessor
from ..infrastructure.processors.rife import (
    RifePytorchWrapper, RifeNcnnWrapper, RifeFallback
)
from ..infrastructure.processors.realesrgan import (
    RealESRGANPytorchWrapper, RealESRGANNcnnWrapper, RealESRGANFallback
)

class ProcessorFactory:
    """
    Фабрика для создания процессоров.
    
    Open/Closed principle: новые процессоры регистрируются,
    не изменяя код фабрики.
    """
    
    def __init__(self):
        self._rife_processors: Dict[str, Type[IProcessor]] = {
            'pytorch': RifePytorchWrapper,
            'ncnn': RifeNcnnWrapper,
            'fallback': RifeFallback
        }
        self._esrgan_processors: Dict[str, Type[IProcessor]] = {
            'pytorch': RealESRGANPytorchWrapper,
            'ncnn': RealESRGANNcnnWrapper,
            'fallback': RealESRGANFallback
        }
    
    def create_interpolator(self, prefer: str = 'auto') -> IProcessor:
        """Создаёт интерполятор с fallback стратегией"""
        
        if prefer == 'auto':
            # Chain of Responsibility: пытаемся в порядке приоритета
            for backend in ['pytorch', 'ncnn', 'fallback']:
                processor_class = self._rife_processors[backend]
                if processor_class.is_available():
                    return processor_class()
        
        processor_class = self._rife_processors.get(prefer)
        if not processor_class:
            raise ValueError(f"Unknown RIFE backend: {prefer}")
        
        return processor_class()
    
    def create_upscaler(self, prefer: str = 'auto') -> IProcessor:
        """Создаёт апскейлер с fallback стратегией"""
        
        if prefer == 'auto':
            for backend in ['pytorch', 'ncnn', 'fallback']:
                processor_class = self._esrgan_processors[backend]
                if processor_class.is_available():
                    return processor_class()
        
        processor_class = self._esrgan_processors.get(prefer)
        if not processor_class:
            raise ValueError(f"Unknown Real-ESRGAN backend: {prefer}")
        
        return processor_class()
```

---

### 3. Infrastructure Layer (Инфраструктурный слой)

#### Base Processor (Template Method)
```python
# src/infrastructure/processors/base.py

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any
from ...domain.models import ProcessingResult
from ...shared.logging import get_logger
from ...shared.metrics import MetricsCollector

class BaseProcessor(ABC):
    """
    Базовый класс для всех процессоров.
    
    Template Method pattern: определяет скелет алгоритма,
    делегируя конкретные шаги подклассам.
    """
    
    def __init__(self, logger=None, metrics=None):
        self._logger = logger or get_logger(self.__class__.__name__)
        self._metrics = metrics or MetricsCollector()
    
    def process(
        self, 
        input_frames: List[Path], 
        output_dir: Path,
        **options
    ) -> ProcessingResult:
        """
        Шаблонный метод для обработки кадров.
        """
        self._logger.info(f"Processing {len(input_frames)} frames")
        
        # 1. Валидация входных данных
        self._validate_inputs(input_frames, options)
        
        # 2. Подготовка окружения
        self._prepare_environment(output_dir)
        
        # 3. Выполнение обработки (делегируется подклассам)
        output_frames = self._execute_processing(
            input_frames, output_dir, options
        )
        
        # 4. Постобработка и валидация результата
        self._validate_outputs(output_frames)
        
        # 5. Сбор метрик
        return self._build_result(output_frames)
    
    @abstractmethod
    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
    ) -> List[Path]:
        """Конкретная реализация обработки (в подклассах)"""
        pass
    
    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Проверяет доступность процессора в текущем окружении"""
        pass
    
    def _validate_inputs(self, frames: List[Path], options: Dict[str, Any]):
        """Базовая валидация входов"""
        if not frames:
            raise ValueError("Input frames list is empty")
        
        for frame in frames:
            if not frame.exists():
                raise FileNotFoundError(f"Frame not found: {frame}")
    
    def _prepare_environment(self, output_dir: Path):
        """Подготовка директорий и окружения"""
        output_dir.mkdir(parents=True, exist_ok=True)
    
    def _validate_outputs(self, output_frames: List[Path]):
        """Валидация выходных данных"""
        if not output_frames:
            raise RuntimeError("No output frames generated")
    
    def _build_result(self, output_frames: List[Path]) -> ProcessingResult:
        """Создаёт объект результата с метриками"""
        return ProcessingResult(
            success=True,
            output_path=output_frames[0].parent,
            frames_processed=len(output_frames),
            duration_seconds=self._metrics.elapsed_time(),
            metrics=self._metrics.get_summary(),
            errors=[]
        )
```

#### RIFE PyTorch Wrapper
```python
# src/infrastructure/processors/rife/pytorch_wrapper.py

import subprocess
from pathlib import Path
from typing import List, Dict, Any
from ..base import BaseProcessor

class RifePytorchWrapper(BaseProcessor):
    """
    Обёртка над PyTorch версией RIFE.
    
    Adapter pattern: адаптирует shell-скрипт к единому интерфейсу.
    """
    
    WRAPPER_SCRIPT = Path("/workspace/project/run_rife_pytorch.sh")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._check_dependencies()
    
    @classmethod
    def is_available(cls) -> bool:
        """Проверяет наличие PyTorch и CUDA"""
        try:
            import torch
            return torch.cuda.is_available() and cls.WRAPPER_SCRIPT.exists()
        except ImportError:
            return False
    
    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
    ) -> List[Path]:
        """Запускает PyTorch RIFE через wrapper"""
        
        # Подготовка параметров
        factor = options.get('factor', 2)
        input_video = self._frames_to_video(input_frames)
        output_video = output_dir / "interpolated.mp4"
        
        # Запуск обёртки
        cmd = [
            str(self.WRAPPER_SCRIPT),
            str(input_video),
            str(output_video),
            str(factor)
        ]
        
        self._logger.info(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=options.get('timeout', 3600)
        )
        
        if result.returncode != 0:
            self._logger.error(f"RIFE failed: {result.stderr}")
            raise RuntimeError(f"RIFE processing failed: {result.stderr}")
        
        # Извлекаем кадры из результата
        return self._video_to_frames(output_video, output_dir)
    
    def _check_dependencies(self):
        """Проверяет необходимые зависимости"""
        if not self.is_available():
            raise RuntimeError("PyTorch RIFE is not available")
```

#### Uploader with Retry
```python
# src/infrastructure/io/uploader.py

import boto3
from pathlib import Path
from typing import Optional
from ...domain.protocols import IUploader
from ...domain.models import UploadResult
from ...domain.exceptions import UploadError
from ...shared.retry import retry_with_backoff
from ...shared.logging import get_logger

class B2S3Uploader(IUploader):
    """
    Загрузчик файлов в Backblaze B2 через S3 API.
    
    Single Responsibility: только загрузка файлов.
    Dependency Inversion: зависит от абстракций (IUploader).
    """
    
    def __init__(
        self,
        bucket: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
        pending_marker_path: Optional[Path] = None,
        logger=None
    ):
        self._bucket = bucket
        self._s3_client = self._create_client(
            endpoint, access_key, secret_key
        )
        self._pending_marker = pending_marker_path or Path("/workspace/.pending_upload.json")
        self._logger = logger or get_logger(self.__class__.__name__)
    
    @retry_with_backoff(max_attempts=3, backoff_seconds=2)
    def upload(self, file_path: Path, key: str) -> UploadResult:
        """
        Загружает файл с автоматическими повторами.
        
        Decorator pattern: retry логика добавлена декоратором.
        """
        self._logger.info(f"Uploading {file_path} to s3://{self._bucket}/{key}")
        
        try:
            # Multipart upload для больших файлов
            transfer_config = boto3.s3.transfer.TransferConfig(
                multipart_threshold=50 * 1024 * 1024,
                multipart_chunksize=50 * 1024 * 1024,
                max_concurrency=4
            )
            
            self._s3_client.upload_file(
                str(file_path),
                self._bucket,
                key,
                Config=transfer_config
            )
            
            # Генерация presigned URL
            url = self._s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self._bucket, 'Key': key},
                ExpiresIn=604800  # 1 week
            )
            
            # Удаляем pending marker при успехе
            self._remove_pending_marker()
            
            return UploadResult(
                success=True,
                url=url,
                bucket=self._bucket,
                key=key,
                size_bytes=file_path.stat().st_size,
                duration_seconds=0  # TODO: measure
            )
            
        except Exception as e:
            # Сохраняем pending marker для retry
            self._save_pending_marker(file_path, key)
            self._logger.error(f"Upload failed: {e}")
            raise UploadError(f"Failed to upload {file_path}: {e}")
    
    def resume_pending(self) -> List[UploadResult]:
        """Возобновляет незавершённые загрузки"""
        if not self._pending_marker.exists():
            return []
        
        # Читаем pending marker и пытаемся загрузить
        # ...
```

---

## Применение принципов SOLID

### Single Responsibility Principle (SRP)
Каждый класс имеет одну причину для изменения:

- `ConfigLoader` — только загрузка и валидация конфигурации
- `VideoExtractor` — только извлечение кадров
- `B2S3Uploader` — только загрузка файлов
- `Orchestrator` — только координация компонентов

**Пример нарушения (было):**
```python
# pipeline.py смешивал всё:
def main():
    # парсинг аргументов
    # загрузка конфига
    # скачивание файла
    # извлечение кадров
    # обработка
    # сборка
    # загрузка
    # логирование
```

**Рефакторинг (стало):**
```python
# Каждый компонент — отдельный класс с единственной ответственностью
orchestrator = VideoProcessingOrchestrator(
    downloader=HttpDownloader(),
    extractor=FFmpegExtractor(),
    upscaler=factory.create_upscaler(),
    # ...
)
```

### Open/Closed Principle (OCP)
Классы открыты для расширения, закрыты для модификации:

**Добавление нового процессора:**
```python
# Новая реализация RIFE (например, TensorRT версия)
class RifeTensorRTWrapper(BaseProcessor):
    @classmethod
    def is_available(cls) -> bool:
        return check_tensorrt_available()
    
    def _execute_processing(self, ...):
        # TensorRT-specific implementation
        pass

# Регистрация в фабрике (не меняя существующий код)
factory.register_rife_backend('tensorrt', RifeTensorRTWrapper)
```

### Liskov Substitution Principle (LSP)
Подклассы могут заменять базовые классы без нарушения поведения:

```python
# Все реализации IProcessor взаимозаменяемы
def process_video(processor: IProcessor, frames: List[Path]):
    # Работает с любой реализацией
    result = processor.process(frames, output_dir)
    assert result.success

# Можно подставить любую реализацию
process_video(RifePytorchWrapper())
process_video(RifeNcnnWrapper())
process_video(RifeFallback())  # Все соблюдают контракт
```

### Interface Segregation Principle (ISP)
Интерфейсы разделены по ролям:

```python
# НЕ делаем один огромный интерфейс:
class IVideoProcessor(Protocol):  # ❌ Плохо
    def download(self, url): ...
    def extract(self, video): ...
    def process(self, frames): ...
    def assemble(self, frames): ...
    def upload(self, file): ...

# ВМЕСТО этого — маленькие специализированные интерфейсы:
class IDownloader(Protocol):  # ✅ Хорошо
    def download(self, url): ...

class IExtractor(Protocol):  # ✅ Хорошо
    def extract(self, video): ...

# Клиенты зависят только от нужных интерфейсов
```

### Dependency Inversion Principle (DIP)
Зависимости направлены на абстракции, а не на конкретные классы:

```python
# Orchestrator зависит от абстракций (protocols)
class VideoProcessingOrchestrator:
    def __init__(
        self,
        downloader: IDownloader,      # ✅ Зависимость на интерфейс
        extractor: IExtractor,         # ✅ Не на конкретный класс
        upscaler: IProcessor,          # ✅
        # ...
    ):
        # Конкретные реализации инжектятся извне (DI)
        self._downloader = downloader
        # ...

# Создание с конкретными реализациями (в точке входа)
orchestrator = VideoProcessingOrchestrator(
    downloader=HttpDownloader(),          # Конкретная реализация
    extractor=FFmpegExtractor(),          # Можно подменить
    upscaler=RealESRGANPytorchWrapper(),  # Легко тестировать с моками
)
```

---

## Диаграммы взаимодействия

### Sequence Diagram: Обработка видео

```
User/CLI -> Runner: process_video(job)
Runner -> ConfigLoader: load_config()
ConfigLoader --> Runner: config
Runner -> Factory: create_orchestrator(config)
Factory --> Runner: orchestrator

Runner -> Orchestrator: process(job)

Orchestrator -> Downloader: download(url)
Downloader --> Orchestrator: local_file

Orchestrator -> Extractor: extract_frames(video)
Extractor --> Orchestrator: frames[]

alt mode == "upscale"
    Orchestrator -> Upscaler: process(frames)
    Upscaler --> Orchestrator: processed_frames[]
else mode == "interp"
    Orchestrator -> Interpolator: process(frames)
    Interpolator --> Orchestrator: processed_frames[]
else mode == "both"
    Orchestrator -> Upscaler: process(frames)
    Upscaler --> Orchestrator: upscaled_frames[]
    Orchestrator -> Interpolator: process(upscaled_frames)
    Interpolator --> Orchestrator: processed_frames[]
end

Orchestrator -> Assembler: assemble(frames, fps)
Assembler --> Orchestrator: output_video

Orchestrator -> Uploader: upload(output_video, key)
Uploader --> Orchestrator: upload_result

Orchestrator --> Runner: processing_result
Runner --> User/CLI: success / failure
```

### Class Diagram: Core Components

```
┌─────────────────────┐
│   IDownloader       │◄────────────────┐
└─────────────────────┘                 │
         △                               │
         │                               │
    ┌────┴────┐                          │
    │         │                          │
HttpDown  S3Down                         │
                                         │
┌─────────────────────┐                 │
│   IExtractor        │◄────────┐       │
└─────────────────────┘         │       │
         △                      │       │
         │                      │       │
    FFmpegExtractor             │       │
                                │       │
┌─────────────────────┐        │       │
│   IProcessor        │◄───┐   │       │
└─────────────────────┘    │   │       │
         △                 │   │       │
         │                 │   │       │
    ┌────┴────┐            │   │       │
    │         │            │   │       │
  RIFE    RealESRGAN       │   │       │
                           │   │       │
┌─────────────────────┐   │   │       │
│   IAssembler        │◄──┤   │       │
└─────────────────────┘   │   │       │
         △                │   │       │
         │                │   │       │
    FFmpegAssembler       │   │       │
                          │   │       │
┌─────────────────────┐  │   │       │
│   IUploader         │◄─┤   │       │
└─────────────────────┘  │   │       │
         △               │   │       │
         │               │   │       │
    B2S3Uploader         │   │       │
                         │   │       │
┌─────────────────────────────────────┤
│  VideoProcessingOrchestrator        │
│  --------------------------------   │
│  - downloader: IDownloader          │
│  - extractor: IExtractor            │
│  - upscaler: IProcessor             │
│  - interpolator: IProcessor         │
│  - assembler: IAssembler            │
│  - uploader: IUploader              │
│  --------------------------------   │
│  + process(job): ProcessingResult   │
└─────────────────────────────────────┘
```

---

## План миграции

### Фаза 1: Подготовка (3-4 дня)
- [ ] Создать структуру каталогов `src/`
- [ ] Определить все интерфейсы в `domain/protocols.py`
- [ ] Создать доменные модели в `domain/models.py`
- [ ] Настроить pytest, coverage, lint
- [ ] Создать skeleton для всех ключевых модулей

### Фаза 2: Infrastructure Layer (5-7 дней)
- [ ] **Config Loader**
  - Перенести логику из текущего `config.yaml` парсинга
  - Добавить валидацию через pydantic
  - Unit-тесты (coverage 90%+)

- [ ] **Uploader**
  - Рефакторинг `upload_b2.py` в `infrastructure/io/uploader.py`
  - Добавить pending marker поддержку
  - Mock boto3 в тестах

- [ ] **Extractor/Assembler**
  - Выделить FFmpeg обёртки
  - Добавить fallback логику (nvenc -> libx264)
  - Mock subprocess в тестах

### Фаза 3: Processors (7-10 дней)
- [ ] **Base Processor**
  - Создать базовый класс с template method
  - Общая валидация и метрики

- [ ] **RIFE Processors**
  - Adapter для PyTorch wrapper (существующий shell-скрипт)
  - Adapter для NCNN wrapper
  - Fallback реализация (ffmpeg minterpolate)
  - Unit-тесты для каждого

- [ ] **Real-ESRGAN Processors**
  - Adapter для PyTorch wrapper
  - Adapter для NCNN wrapper
  - Fallback реализация
  - Unit-тесты

### Фаза 4: Application Layer (4-5 дней)
- [ ] **Orchestrator**
  - Создать главный класс координации
  - Реализовать логику `mode` (upscale/interp/both)
  - Strategy pattern для порядка операций
  - Integration тесты

- [ ] **Factories**
  - ProcessorFactory с auto-detection
  - Регистрация всех реализаций
  - Unit-тесты

### Фаза 5: Presentation Layer (2-3 дня)
- [ ] **CLI**
  - Thin wrapper над Orchestrator
  - Аргументы командной строки
  - Logging и progress reporting

- [ ] **Container Runner**
  - Entrypoint для Docker контейнера
  - ENV -> Config преобразование
  - Graceful shutdown handling

### Фаза 6: Integration & Testing (5-7 дней)
- [ ] **Integration Tests**
  - End-to-end тесты с реальными видео (малыми)
  - Smoke tests для контейнера
  - CI pipeline (GitHub Actions / GitLab CI)

- [ ] **Performance Testing**
  - Бенчмарки обработки
  - Метрики использования VRAM
  - Профилирование узких мест

### Фаза 7: Migration & Cleanup (3-4 дня)
- [ ] Постепенная замена старого кода
- [ ] Backward compatibility слой
- [ ] Обновление документации
- [ ] Code review и cleanup

**Общее время: 29-40 дней (1.5-2 месяца при работе в одиночку)**

---

## Тестирование

### Стратегия тестирования

#### Unit Tests (80% coverage minimum)
```python
# tests/unit/test_processors/test_rife_pytorch.py

import pytest
from unittest.mock import Mock, patch
from src.infrastructure.processors.rife import RifePytorchWrapper

@pytest.fixture
def mock_subprocess():
    with patch('subprocess.run') as mock:
        yield mock

@pytest.fixture
def processor():
    return RifePytorchWrapper()

def test_process_success(processor, mock_subprocess, tmp_path):
    # Arrange
    input_frames = [tmp_path / f"frame_{i:04d}.png" for i in range(10)]
    for frame in input_frames:
        frame.touch()
    
    output_dir = tmp_path / "output"
    mock_subprocess.return_value = Mock(returncode=0, stdout="", stderr="")
    
    # Act
    result = processor.process(input_frames, output_dir, factor=2)
    
    # Assert
    assert result.success
    assert result.frames_processed > 0
    mock_subprocess.assert_called_once()

def test_process_failure(processor, mock_subprocess, tmp_path):
    # Arrange
    input_frames = [tmp_path / "frame.png"]
    input_frames[0].touch()
    
    output_dir = tmp_path / "output"
    mock_subprocess.return_value = Mock(
        returncode=1, 
        stdout="", 
        stderr="CUDA error"
    )
    
    # Act & Assert
    with pytest.raises(RuntimeError, match="CUDA error"):
        processor.process(input_frames, output_dir)
```

#### Integration Tests
```python
# tests/integration/test_orchestrator.py

import pytest
from src.application.orchestrator import VideoProcessingOrchestrator
from src.application.factories import ProcessorFactory
from src.domain.models import ProcessingJob

@pytest.mark.integration
def test_full_upscale_pipeline(sample_video, config):
    # Arrange
    factory = ProcessorFactory()
    orchestrator = factory.create_orchestrator(config)
    
    job = ProcessingJob(
        job_id="test-001",
        input_url=str(sample_video),
        mode="upscale",
        scale=2.0,
        # ...
    )
    
    # Act
    result = orchestrator.process(job)
    
    # Assert
    assert result.success
    assert result.output_path.exists()
    # Проверяем качество выхода
    assert get_video_resolution(result.output_path) == (1920, 1080)
```

#### Smoke Tests (Docker)
```bash
# tests/smoke/run_smoke.sh

#!/bin/bash
set -e

echo "Building container..."
docker build -t pipeline:test .

echo "Running smoke test..."
docker run --rm \
  -e INPUT_URL="http://example.com/test_5s.mp4" \
  -e MODE="upscale" \
  -e SCALE="2" \
  pipeline:test

echo "✅ Smoke test passed"
```

---

## Метрики качества

### Code Quality Metrics

#### Цели
- **Test Coverage**: ≥ 80% общий, ≥ 95% для критических компонентов
- **Cyclomatic Complexity**: ≤ 10 на функцию
- **Code Duplication**: ≤ 3%
- **Maintainability Index**: ≥ 65
- **Type Coverage** (mypy): 100%

#### Инструменты
```bash
# Coverage
pytest --cov=src --cov-report=html --cov-report=term

# Linting
pylint src/ --rcfile=.pylintrc
flake8 src/
black src/ --check
isort src/ --check-only

# Type checking
mypy src/ --strict

# Complexity
radon cc src/ -s -a

# Security
bandit -r src/
```

### Performance Metrics

#### Целевые показатели
- Overhead оркестратора: < 5% от общего времени
- Время старта контейнера: < 10 секунд
- Memory leak: 0 (valgrind/memory_profiler)
- VRAM utilization: > 90% при batch обработке

#### Мониторинг
```python
# src/shared/metrics.py

from dataclasses import dataclass
from time import time
from typing import Dict, Any

@dataclass
class ProcessingMetrics:
    total_duration: float
    download_duration: float
    extraction_duration: float
    processing_duration: float
    assembly_duration: float
    upload_duration: float
    
    frames_processed: int
    fps_avg: float
    vram_peak_mb: float
    
    def overhead_percentage(self) -> float:
        processing_time = (
            self.download_duration +
            self.extraction_duration +
            self.processing_duration +
            self.assembly_duration +
            self.upload_duration
        )
        overhead = self.total_duration - processing_time
        return (overhead / self.total_duration) * 100
```

---

## Чеклист готовности к миграции

### Инфраструктура
- [ ] CI/CD pipeline настроен
- [ ] Docker образ собирается
- [ ] Тесты запускаются в CI
- [ ] Линтеры и type checker интегрированы
- [ ] Документация актуализирована

### Код
- [ ] Все интерфейсы определены
- [ ] Все ключевые компоненты реализованы
- [ ] Unit тесты покрывают > 80%
- [ ] Integration тесты проходят
- [ ] Smoke tests в контейнере работают

### Backward Compatibility
- [ ] Старые скрипты работают через адаптеры
- [ ] ENV переменные поддерживаются
- [ ] Формат config.yaml совместим
- [ ] Миграционная документация написана

### Performance
- [ ] Нет деградации производительности
- [ ] Memory leaks отсутствуют
- [ ] VRAM использование оптимально
- [ ] Логи не засоряют диск

### Documentation
- [ ] README обновлён
- [ ] API документация (docstrings)
- [ ] Architecture decision records (ADR)
- [ ] Deployment guide

---

## Риски и митигации

### Технические риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Регрессия функциональности | Высокая | Высокое | Extensive integration tests, gradual rollout |
| Performance degradation | Средняя | Высокое | Benchmarks перед/после, профилирование |
| Breaking changes API | Высокая | Среднее | Backward compatibility layer |
| Incomplete migration | Средняя | Высокое | Поэтапная миграция, MVP подход |

### Организационные риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Увеличение времени разработки | Высокая | Среднее | Realistic timeline, buffer time |
| Knowledge gaps | Средняя | Среднее | Documentation, pair programming |
| Scope creep | Средняя | Высокое | Чёткие границы фаз, MVP focus |

---

## Следующие шаги (Action Items)

### Немедленно (эта неделя)
1. ✅ Создать `oop3.md` с детальным планом
2. [ ] Создать feature branch `refactor/oop-solid`
3. [ ] Настроить структуру `src/` каталогов
4. [ ] Определить все протоколы в `domain/protocols.py`
5. [ ] Настроить pytest и coverage

### Короткий срок (следующие 2 недели)
6. [ ] Реализовать Config Loader + тесты
7. [ ] Рефакторинг Uploader + тесты
8. [ ] Создать BaseProcessor template
9. [ ] Адаптеры для RIFE/Real-ESRGAN
10. [ ] Первая версия Orchestrator

### Средний срок (месяц)
11. [ ] Полная migration всех процессоров
12. [ ] Integration tests
13. [ ] Smoke tests в CI
14. [ ] Performance benchmarks
15. [ ] Backward compatibility layer

### Долгий срок (2 месяца)
16. [ ] Полная замена старого кода
17. [ ] Cleanup legacy scripts
18. [ ] Production deployment
19. [ ] Мониторинг и метрики
20. [ ] Documentation finalization

---

## Заключение

Данный рефакторинг преобразует проект из "спагетти-кода" в чистую, тестируемую, расширяемую архитектуру, основанную на принципах SOLID. Ключевые преимущества:

✅ **Maintainability**: легко понимать и изменять  
✅ **Testability**: каждый компонент изолированно тестируется  
✅ **Extensibility**: новые фичи добавляются без изменения существующего кода  
✅ **Reliability**: robust error handling и retry mechanisms  
✅ **Performance**: оптимизация без ущерба для читаемости  

**Общая оценка трудоёмкости**: 1.5-2 месяца при работе в одиночку, 3-4 недели при команде из 2-3 разработчиков.

---

_Документ подготовлен: 1 декабря 2025_  
_Версия: 1.0_  
_Автор: GitHub Copilot (AI Assistant)_

