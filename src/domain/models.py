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
class Frame:
    """Represents a single video frame."""

    path: Path
    index: int
    timestamp: float

    def exists(self) -> bool:
        """Check if frame file exists."""
        return self.path.exists()


@dataclass
class Job:
    """Represents a media processing job."""

    job_id: str
    input_url: str
    type: str = 'video'  # 'video', 'image', 'audio'
    mode: str = 'upscale'  # depends on type
    # Video-specific
    scale: float = 2.0
    target_fps: Optional[int] = None
    interp_factor: float = 2.0
    strategy: str = 'interp-then-upscale'
    # Audio-specific
    audio_mode: str = 'remove_reverb'  # 'remove_reverb', 'enhance', 'normalize'
    # Image-specific
    image_mode: str = 'upscale'  # 'upscale', 'hdr', 'denoise'
    # Common
    prefer: str = 'auto'
    created_at: datetime = field(default_factory=datetime.now)
    config: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Validate type
        if self.type not in ('video', 'image', 'audio'):
            raise ValueError(f"Invalid type: {self.type}. Must be 'video', 'image', or 'audio'")
        
        # Validate based on type
        if self.type == 'video':
            if self.mode not in ('upscale', 'interp', 'both', 'remove-subtitles'):
                raise ValueError(f"Invalid video mode: {self.mode}")
            if self.scale <= 0:
                raise ValueError("Scale must be positive")
            if self.mode == 'both' and self.strategy not in ('interp-then-upscale', 'upscale-then-interp'):
                raise ValueError(f"Invalid strategy: {self.strategy}")
        elif self.type == 'image':
            if self.mode not in ('upscale', 'hdr', 'denoise'):
                raise ValueError(f"Invalid image mode: {self.mode}")
            if self.scale <= 0:
                raise ValueError("Scale must be positive")
        elif self.type == 'audio':
            if self.mode not in ('remove_reverb', 'enhance', 'normalize'):
                raise ValueError(f"Invalid audio mode: {self.mode}")
