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
    MASK_DILATION: int = 12
    USE_GPU: bool = True  # Disable GPU completely to save memory
    USE_GPU_FOR_OCR: bool = True
    CONFIDENCE_THRESHOLD: float = 0.3
    
    # Processing settings - optimized for RTX 3080 Ti 12GB
    BATCH_SIZE: int = 4  # Process 4 frames at a time for better GPU utilization
    MAX_FRAMES_PER_CHUNK: int = 20  # Larger chunks for better performance
    
    # Device settings
    FORCE_CPU: bool = False  # Force CPU usage to avoid GPU memory issues
    
    # Downscaling settings
    AUTO_DOWNSCALE: bool = True  # Automatically downscale high-resolution videos to prevent OOM
    MAX_HEIGHT: int = 720  # Maximum frame height before downscaling (pixels)
    
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
