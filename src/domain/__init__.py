"""Domain layer package."""

from .models import Video, ProcessingResult, UploadResult, Job, Frame
from .exceptions import (
    DomainException,
    VideoProcessingError,
    DownloadError,
    UploadError,
    ConfigurationError,
    ExtractionError,
    AssemblyError,
    ProcessorNotAvailableError,
)
from .protocols import (
    IDownloader,
    IExtractor,
    IProcessor,
    IAssembler,
    IUploader,
    ITempStorage,
    ILogger,
    IMetricsCollector,
)

__all__ = [
    # Models
    "Video",
    "ProcessingResult",
    "UploadResult",
    "Job",
    "Frame",
    # Exceptions
    "DomainException",
    "VideoProcessingError",
    "DownloadError",
    "UploadError",
    "ConfigurationError",
    "ExtractionError",
    "AssemblyError",
    "ProcessorNotAvailableError",
    # Protocols
    "IDownloader",
    "IExtractor",
    "IProcessor",
    "IAssembler",
    "IUploader",
    "ITempStorage",
    "ILogger",
    "IMetricsCollector",
]
