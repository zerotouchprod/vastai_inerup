"""Domain models for video processing."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass(frozen=True)
class Video:
    """Represents a video file with metadata."""

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
        if self.duration < 0:
            raise ValueError("Duration cannot be negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive")


@dataclass
class ProcessingResult:
    """Result of a processing operation."""

    success: bool
    output_path: Optional[Path] = None
    frames_processed: int = 0
    duration_seconds: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message to the result."""
        self.errors.append(error)

    def add_metric(self, key: str, value: Any) -> None:
        """Add a metric to the result."""
        self.metrics[key] = value


@dataclass
class UploadResult:
    """Result of a file upload operation."""

    success: bool
    url: Optional[str] = None
    bucket: str = ""
    key: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class ProcessingJob:
    """Represents a video processing job."""

    job_id: str
    input_url: str
    mode: str  # 'upscale', 'interp', 'both'
    scale: float = 2.0
    target_fps: Optional[int] = None
    interp_factor: float = 2.0
    prefer: str = 'auto'
    strategy: str = 'interp-then-upscale'
    created_at: datetime = field(default_factory=datetime.now)
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in ('upscale', 'interp', 'both'):
            raise ValueError(f"Invalid mode: {self.mode}")
        if self.scale <= 0:
            raise ValueError("Scale must be positive")


@dataclass
class Frame:
    """Represents a single video frame."""

    path: Path
    index: int
    timestamp: float

    def exists(self) -> bool:
        """Check if frame file exists."""
        return self.path.exists()

