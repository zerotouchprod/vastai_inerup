"""
Configuration module for subtitle removal application.
Uses Pydantic BaseSettings for environment variable support.
"""

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import Optional


class InpaintingEngine(str, Enum):
    """Available inpainting engines."""
    PROPAINTER = "propainter"
    LAMA = "lama"
    STTN = "sttn"


class AppConfig(BaseSettings):
    """Application configuration."""
    
    # Inpainting engine selection
    INPAINTING_ENGINE: InpaintingEngine = InpaintingEngine.LAMA
    
    # ProPainter settings
    # https://github.com/gnimuyeh/ProPainter-Wire
    # Priority: 
    # 1. ENV variable PROPAINTER_ROOT
    # 2. Local folder in project root (for dev)
    # 3. System folder /opt/ProPainter-Wire (for docker)
    # 4. Legacy fallback /opt/ProPainter
    PROPAINTER_ROOT: Path = Path("/opt/ProPainter-Wire")
    
    @property
    def INFERENCE_SCRIPT(self) -> Optional[Path]:
        """Get path to inference_core.py script."""
        import os
        possible_paths = [
            os.getenv("PROPAINTER_ROOT"),
            os.path.join(os.getcwd(), "ProPainter-Wire"),
            "/opt/ProPainter-Wire",
            "/opt/ProPainter"  # Legacy fallback
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path):
                propainter_dir = Path(path)
                inference_script = propainter_dir / "inference_core.py"
                if inference_script.exists():
                    return inference_script
        
        return None
    
    @property
    def PROPAINTER_DIR(self) -> Optional[Path]:
        """Get ProPainter directory path."""
        import os
        possible_paths = [
            os.getenv("PROPAINTER_ROOT"),
            os.path.join(os.getcwd(), "ProPainter-Wire"),
            "/opt/ProPainter-Wire",
            "/opt/ProPainter"  # Legacy fallback
        ]
        
        for path in possible_paths:
            if path and os.path.exists(path):
                return Path(path)
        
        return None
    
    # LaMa settings
    LAMA_MODEL_PATH: Path = Path("/opt/lama_models/big-lama.pt")
    LAMA_TEMPORAL_SMOOTHING: bool = True
    LAMA_SMOOTHING_WINDOW: int = 3
    LAMA_SMOOTHING_WEIGHTS: str = "0.2,0.6,0.2"  # Weights for sliding window blending
    
    # STTN settings
    STTN_MODEL_PATH: Path = Path("/opt/sttn_models/sttn.pth")
    STTN_CHUNK_SIZE: int = 20  # Larger chunks for better temporal consistency
    STTN_OVERLAP: int = 2
    
    # OCR settings
    OCR_LANG: str = "en"
    MASK_DILATION: int = 15  # 30 Increased to cover text shadows/artifacts (sledgehammer approach)
    USE_GPU: bool = True  # Disable GPU completely to save memory
    USE_GPU_FOR_OCR: bool = True
    CONFIDENCE_THRESHOLD: float = 0.1  # Lowered for aggressive detection
    
    # OCR detector parameters (EasyOCR)
    OCR_TEXT_THRESHOLD: float = 0.05  # Default 0.7. Lower -> more sensitive to faint text
    OCR_LOW_TEXT: float = 0.05        # Default 0.4. Lower -> detect faint characters
    OCR_LINK_THRESHOLD: float = 0.2   # Default 0.4. Lower -> merge characters into words
    OCR_CANVAS_SIZE: int = 2560       # Default 2560. Larger -> preserve small text details
    OCR_MAG_RATIO: float = 1.5        # Default 1.0. Zoom image before detection (helps small text)
    OCR_THRESHOLD: float = 0.1        # Default 0.2. Lower -> more sensitive binarization
    OCR_BBOX_MIN_SCORE: float = 0.2   # Default 0.2. Lower -> keep more candidate boxes
    OCR_BBOX_MIN_SIZE: int = 3        # Default 3. Minimum box size in pixels
    OCR_MAX_CANDIDATES: int = 0       # Default 0 (unlimited)
    OCR_SLOPE_THS: float = 0.1        # Default 0.1. Slope threshold for text orientation
    OCR_YCENTER_THS: float = 0.5      # Default 0.5. Y-center threshold
    OCR_HEIGHT_THS: float = 0.5       # Default 0.5. Height threshold
    OCR_WIDTH_THS: float = 0.5        # Default 0.5. Width threshold
    OCR_ADD_MARGIN: float = 0.1       # Default 0.1. Add margin around text
    
    # Dynamic cropping settings
    PADDING_PX: int = 32  # Padding around subtitle bounding box for context
    MAX_CROP_AREA_RATIO: float = 0.4  # Maximum allowed crop area as ratio of total frame area (40%)
    
    # Processing settings - optimized for RTX 3080 Ti 12GB
    BATCH_SIZE: int = 1  # Process 4 frames at a time for better GPU utilization
    MAX_FRAMES_PER_CHUNK: int = 10  # Larger chunks for better performance
    PROPAINTER_OVERLAP: int = 2  # Overlap between chunks for smooth transitions
    
    # Device settings
    FORCE_CPU: bool = False  # Force CPU usage to avoid GPU memory issues
    
    # Downscaling settings
    AUTO_DOWNSCALE: bool = True  # Automatically downscale high-resolution videos to prevent OOM
    MAX_HEIGHT: int = 1536  # Maximum frame height before downscaling (pixels) - increased for 1080p support
    
    # ROI (Region of Interest) settings
    USE_ROI_OPTIMIZATION: bool = True  # Process only bottom region where subtitles appear
    ROI: str = "0.05,0.70,0.90,0.25"  # Region of Interest: x,y,w,h (0.0-1.0) - bottom 25% of screen
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

    # AMP (Automatic Mixed Precision) settings for memory optimization
    # Note: AMP requires modification of ProPainter script to use torch.cuda.amp.autocast
    USE_AMP: bool = False  # Disabled by default as it requires ProPainter modification
    
    # Force FP32 precision (disable AMP even if USE_AMP=True)
    FORCE_FP32: bool = False
    
    # Debug settings
    SAVE_MASKED_PREVIEW: bool = False  # Save masked input frames for debugging

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
