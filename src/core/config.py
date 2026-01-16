"""
Configuration module for subtitle removal application.
Uses Pydantic BaseSettings for environment variable support.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional


class AppConfig(BaseSettings):
    """Application configuration."""
    
    # ProPainter settings
    PROPAINTER_ROOT: Path = Path("/opt/ProPainter")
    
    # OCR settings
    OCR_LANG: str = "en"
    MASK_DILATION: int = 15  # 30 Increased to cover text shadows/artifacts (sledgehammer approach)
    USE_GPU: bool = True  # Disable GPU completely to save memory
    USE_GPU_FOR_OCR: bool = True
    CONFIDENCE_THRESHOLD: float = 0.1  # Lowered for aggressive detection
    
    # Dynamic cropping settings
    PADDING_PX: int = 32  # Padding around subtitle bounding box for context
    MAX_CROP_AREA_RATIO: float = 0.4  # Maximum allowed crop area as ratio of total frame area (40%)
    
    # Processing settings - optimized for RTX 3080 Ti 12GB
    BATCH_SIZE: int = 1  # Process 4 frames at a time for better GPU utilization
    MAX_FRAMES_PER_CHUNK: int = 6  # Larger chunks for better performance
    PROPAINTER_OVERLAP: int = 2  # Overlap between chunks for smooth transitions
    
    # Device settings
    FORCE_CPU: bool = False  # Force CPU usage to avoid GPU memory issues
    
    # Downscaling settings
    AUTO_DOWNSCALE: bool = True  # Automatically downscale high-resolution videos to prevent OOM
    MAX_HEIGHT: int = 1280  # Maximum frame height before downscaling (pixels)
    
    # ROI (Region of Interest) settings
    USE_ROI_OPTIMIZATION: bool = True  # Process only bottom region where subtitles appear
    ROI: str = "bottom"  # Region of Interest: "bottom", "top", "full", or "x,y,w,h" (0.0-1.0)
    ROI_ZONE_HEIGHT_RATIO: float = 0.4  # Height of each zone for dynamic multi-zone ROI (top/middle/bottom)
    
    # Audio preservation settings (v2.0.1+)
    PRESERVE_AUDIO: bool = True  # Enable audio preservation during video processing
    AUDIO_CODEC: str = "aac"     # Output audio codec
    AUDIO_BITRATE: str = "192k"  # Audio bitrate
    FALLBACK_TO_SILENT: bool = True  # Create silent video if audio processing fails

    # Animated Text Detection settings (v2.1+) - EXPERIMENTAL
    USE_OPTICAL_FLOW: bool = False  # Enable optical flow for animated/moving text (OFF by default)
    OPTICAL_FLOW_KEYFRAME_INTERVAL: int = 5  # OCR every N frames (5 = 2.1x speedup)
    OPTICAL_FLOW_MAX_DIMENSION: int = 1280  # Max resolution for flow computation (prevents OOM on 4K)
    OPTICAL_FLOW_COLOR_THRESHOLD: float = 50.0  # Threshold for karaoke color change detection
    OPTICAL_FLOW_MOTION_THRESHOLD: float = 5.0  # Threshold for moving text detection (pixels)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra fields in .env file
    )


# Global configuration instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get or create configuration instance."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
