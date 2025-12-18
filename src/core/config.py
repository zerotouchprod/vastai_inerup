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
    USE_GPU: bool = True
    USE_GPU_FOR_OCR: bool = False
    CONFIDENCE_THRESHOLD: float = 0.3
    
    # Processing settings
    BATCH_SIZE: int = 4  # Reduced from 8 to save memory
    MAX_FRAMES_PER_CHUNK: int = 20  # Reduced from 30 to save memory
    
    # Device settings
    FORCE_CPU: bool = False
    
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
