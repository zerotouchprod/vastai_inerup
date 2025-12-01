"""Protocol definitions for dependency inversion."""

from typing import Protocol, List, Optional
from pathlib import Path
from .models import Video, ProcessingResult, UploadResult, Frame


class IDownloader(Protocol):
    """Interface for downloading files."""

    def download(self, url: str, destination: Path) -> Path:
        """Download a file from URL to destination."""
        ...

    def supports(self, url: str) -> bool:
        """Check if this downloader supports the given URL."""
        ...


class IExtractor(Protocol):
    """Interface for extracting frames from video."""

    def extract_frames(self, video: Video, output_dir: Path) -> List[Frame]:
        """Extract frames from video to output directory."""
        ...

    def get_video_info(self, video_path: Path) -> Video:
        """Get metadata about a video file."""
        ...

    def get_fps(self, video_path: Path) -> float:
        """Get frames per second of a video."""
        ...

    def get_duration(self, video_path: Path) -> float:
        """Get duration of a video in seconds."""
        ...


class IProcessor(Protocol):
    """Base interface for frame processors (upscalers, interpolators)."""

    def process(
        self,
        input_frames: List[Path],
        output_dir: Path,
        **options
    ) -> ProcessingResult:
        """Process input frames and save results to output directory."""
        ...

    def supports_gpu(self) -> bool:
        """Check if GPU acceleration is available."""
        ...

    @classmethod
    def is_available(cls) -> bool:
        """Check if this processor can be used in current environment."""
        ...


class IAssembler(Protocol):
    """Interface for assembling video from frames."""

    def assemble(
        self,
        frames: List[Path],
        output_path: Path,
        fps: float,
        **options
    ) -> Path:
        """Assemble frames into a video file."""
        ...

    def supports_encoder(self, encoder: str) -> bool:
        """Check if specific encoder is available."""
        ...


class IUploader(Protocol):
    """Interface for uploading files to cloud storage."""

    def upload(self, file_path: Path, key: str) -> UploadResult:
        """Upload a file to cloud storage."""
        ...

    def resume_pending(self) -> List[UploadResult]:
        """Resume any pending uploads from previous runs."""
        ...


class ITempStorage(Protocol):
    """Interface for managing temporary storage."""

    def create_workspace(self, job_id: str) -> Path:
        """Create a temporary workspace for a job."""
        ...

    def cleanup(self, workspace: Path, keep_on_error: bool = False) -> None:
        """Clean up a workspace directory."""
        ...

    def get_workspace(self, job_id: str) -> Optional[Path]:
        """Get existing workspace for a job if it exists."""
        ...


class ILogger(Protocol):
    """Interface for logging."""

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        ...

    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        ...

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        ...

    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        ...

    def exception(self, message: str, **kwargs) -> None:
        """Log exception with traceback."""
        ...


class IMetricsCollector(Protocol):
    """Interface for collecting metrics."""

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        ...

    def stop_timer(self, name: str) -> float:
        """Stop a named timer and return elapsed time."""
        ...

    def record_metric(self, name: str, value: float) -> None:
        """Record a metric value."""
        ...

    def get_summary(self) -> dict:
        """Get summary of all metrics."""
        ...

    def elapsed_time(self) -> float:
        """Get total elapsed time since start."""
        ...

