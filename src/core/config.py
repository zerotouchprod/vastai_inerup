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
    #MASK_DILATION: int = 7  # 15,  30 Increased to cover text shadows/artifacts (sledgehammer approach)
    #CONFIDENCE_THRESHOLD: float = 0.1  # Lowered for aggressive detection
    OCR_LANG: str = "en"
    USE_GPU: bool = True  # Disable GPU completely to save memory
    USE_GPU_FOR_OCR: bool = True

    # Default settings
    # OCR detector parameters (EasyOCR)
    # OCR_TEXT_THRESHOLD: float = 0.05  # Default 0.7. Lower -> more sensitive to faint text
    # OCR_LOW_TEXT: float = 0.05        # Default 0.4. Lower -> detect faint characters
    # OCR_LINK_THRESHOLD: float = 0.2   # Default 0.4. Lower -> merge characters into words
    # OCR_CANVAS_SIZE: int = 2560       # Default 2560. Larger -> preserve small text details
    # OCR_MAG_RATIO: float = 1.5        # Default 1.0. Zoom image before detection (helps small text)
    # OCR_THRESHOLD: float = 0.1        # Default 0.2. Lower -> more sensitive binarization
    # OCR_BBOX_MIN_SCORE: float = 0.2   # Default 0.2. Lower -> keep more candidate boxes
    # OCR_BBOX_MIN_SIZE: int = 3        # Default 3. Minimum box size in pixels
    # OCR_MAX_CANDIDATES: int = 0       # Default 0 (unlimited)
    # OCR_SLOPE_THS: float = 0.1        # Default 0.1. Slope threshold for text orientation
    # OCR_YCENTER_THS: float = 0.5      # Default 0.5. Y-center threshold
    # OCR_HEIGHT_THS: float = 0.5       # Default 0.5. Height threshold
    # OCR_WIDTH_THS: float = 0.5        # Default 0.5. Width threshold
    # OCR_ADD_MARGIN: float = 0.1       # Default 0.1. Add margin around text



    # Профиль "Агрессивный для свечения" - игнорирование полупрозрачных краёв
    # MASK_DILATION: int = 5
    # CONFIDENCE_THRESHOLD: float = 0.3
    # OCR_TEXT_THRESHOLD: float = 0.3
    # OCR_LOW_TEXT: float = 0.3
    # OCR_LINK_THRESHOLD: float = 0.4
    # OCR_MAG_RATIO: float = 1.0
    # OCR_CANVAS_SIZE: int = 1280
    # OCR_THRESHOLD: float = 0.2
    # OCR_BBOX_MIN_SCORE: float = 0.3
    # OCR_BBOX_MIN_SIZE: int = 8
    # OCR_MAX_CANDIDATES: int = 500
    # OCR_SLOPE_THS: float = 0.2
    # OCR_YCENTER_THS: float = 0.7
    # OCR_HEIGHT_THS: float = 0.7
    # OCR_WIDTH_THS: float = 0.7
    # OCR_ADD_MARGIN: float = 0.05

    # =============================================================================
    # OCR DETECTION SENSITIVITY (from subtitle_removal_config.py)
    # =============================================================================
    
    # Minimum confidence threshold for OCR text detection (0.0 to 1.0)
    # Lower = more aggressive (catches more text, including false positives)
    # Higher = more conservative (misses some subtle text)
    # Default: 0.05 (very aggressive, catches short words like "на", "и", "в")
    # Recommended range: 0.01 (ultra-aggressive) to 0.15 (conservative)
    OCR_CONFIDENCE_THRESHOLD: float = 0.12
    
    # Run OCR on both enhanced and original images (True = better detection, 2x slower)
    # When True: runs CLAHE enhancement + original, merges results
    # When False: runs only on enhanced image
    # Default: True (catches text that is visible in only one variant)
    OCR_DUAL_PASS_ENABLED: bool = True
    
    # IoU threshold for merging duplicate detections from dual-pass OCR
    # Higher = stricter deduplication (may keep near-duplicates)
    # Lower = aggressive deduplication (may merge distinct boxes)
    # Default: 0.3 (30% overlap = considered duplicate)
    # Recommended range: 0.2 to 0.5
    OCR_DUPLICATE_IOU_THRESHOLD: float = 0.3
    
    # =============================================================================
    # BOUNDING BOX EXPANSION
    # =============================================================================
    
    # Horizontal expansion around detected text (pixels)
    # Catches text glow, shadows, outline effects
    # Default: 15px
    # Recommended range: 5px (minimal) to 30px (aggressive)
    BBOX_EXPAND_HORIZONTAL: int = 15
    
    # Vertical expansion around detected text (pixels)
    # Catches descenders, ascenders, vertical glow
    # Default: 20px
    # Recommended range: 10px (minimal) to 40px (aggressive)
    BBOX_EXPAND_VERTICAL: int = 20
    
    # =============================================================================
    # MASK DILATION (VRAM-ADAPTIVE)
    # =============================================================================
    
    # Kernel size for <8GB VRAM (e.g., RTX 3060, RTX 4060)
    # Smaller = less aggressive, faster, lower memory usage
    # Default: 30x30
    KERNEL_SIZE_LOW_VRAM: int = 30
    
    # Kernel size for 8-16GB VRAM (e.g., RTX 3080, RTX 4070)
    # Balanced between coverage and performance
    # Default: 40x40
    KERNEL_SIZE_MID_VRAM: int = 40
    
    # Kernel size for >16GB VRAM (e.g., RTX 4090, RTX 5090)
    # Larger = more aggressive, captures full glow/shadow extent
    # Default: 45x45
    KERNEL_SIZE_HIGH_VRAM: int = 45
    
    # Number of dilation iterations (applied BEFORE morphological closing)
    # Higher = more aggressive expansion of mask
    # Default: 2
    # Recommended range: 1 (conservative) to 3 (aggressive)
    DILATION_ITERATIONS_INITIAL: int = 2
    
    # Number of morphological closing iterations (fills gaps between letters)
    # Higher = fills larger gaps (good for spaced text, bad for separate objects)
    # Default: 1
    # Recommended range: 1 to 2
    MORPHOLOGICAL_CLOSING_ITERATIONS: int = 1
    
    # Number of final dilation iterations (applied AFTER closing)
    # Higher = further expansion of final mask
    # Default: 1
    # Recommended range: 0 (no final dilation) to 2 (aggressive)
    DILATION_ITERATIONS_FINAL: int = 1
    
    # =============================================================================
    # CLAHE ENHANCEMENT (for OCR preprocessing)
    # =============================================================================
    
    # CLAHE clip limit (controls contrast enhancement strength)
    # Higher = stronger enhancement (may introduce noise)
    # Lower = gentler enhancement (may miss low-contrast text)
    # Default: 4.0
    # Recommended range: 2.0 (gentle) to 6.0 (aggressive)
    CLAHE_CLIP_LIMIT: float = 4.0
    
    # CLAHE tile grid size (smaller = more localized enhancement)
    # Default: (8, 8)
    # Alternative: (4, 4) for finer detail, (16, 16) for smoother
    CLAHE_TILE_GRID_SIZE: tuple = (8, 8)
    
    # =============================================================================
    # MEMORY OPTIMIZATION
    # =============================================================================
    
    # GPU memory cleanup interval (frames)
    # Run torch.cuda.empty_cache() every N frames
    # Lower = more frequent cleanup (slower, but safer for low-VRAM GPUs)
    # Higher = less frequent cleanup (faster, but may OOM on 6GB GPUs)
    # Default: 50
    # Recommended range: 20 (RTX 3060) to 100 (RTX 4090)
    GPU_CLEANUP_INTERVAL: int = 50
    
    # =============================================================================
    # PROGRESS LOGGING
    # =============================================================================
    
    # Log progress every N% of frames
    # Lower = more frequent logs (verbose)
    # Higher = less frequent logs (cleaner output)
    # Default: 10 (log at 10%, 20%, 30%, etc.)
    PROGRESS_LOG_PERCENTAGE: int = 10
    
    # =============================================================================
    # DEBUG MODE SETTINGS
    # =============================================================================
    
    # Number of example filtered boxes to log per frame (DEBUG level only)
    # Lower = cleaner logs
    # Higher = more diagnostic info
    # Default: 3
    DEBUG_MAX_FILTERED_EXAMPLES: int = 3
    
    # =============================================================================
    # LEGACY OCR PARAMETERS (for backward compatibility)
    # =============================================================================
    
    # Legacy OCR parameters - kept for compatibility with existing .env files
    OCR_TEXT_THRESHOLD: float = 0.15
    OCR_LOW_TEXT: float = 0.15
    OCR_LINK_THRESHOLD: float = 0.25
    OCR_MAG_RATIO: float = 1.3
    OCR_CANVAS_SIZE: int = 2240
    MASK_DILATION: int = 8
    CONFIDENCE_THRESHOLD: float = 0.12
    OCR_THRESHOLD: float = 0.15
    OCR_BBOX_MIN_SCORE: float = 0.2
    OCR_BBOX_MIN_SIZE: int = 4
    OCR_MAX_CANDIDATES: int = 1000
    OCR_SLOPE_THS: float = 0.15
    OCR_YCENTER_THS: float = 0.6
    OCR_HEIGHT_THS: float = 0.6
    OCR_WIDTH_THS: float = 0.6
    OCR_ADD_MARGIN: float = 0.08

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
        extra="ignore",  # Ignore extra fields in .env file
        # Support aliases for backward compatibility
        alias_generator=lambda field_name: {
            # Map legacy parameter names to new names
            'CONFIDENCE_THRESHOLD': 'OCR_CONFIDENCE_THRESHOLD',
            'MASK_DILATION': 'DILATION_ITERATIONS_INITIAL',
            'OCR_ADD_MARGIN': 'BBOX_EXPAND_HORIZONTAL',  # Approximate mapping
        }.get(field_name, field_name)
    )
    
    @classmethod
    def from_env_file(cls, env_file: str = ".env"):
        """Load configuration from specific .env file."""
        import os
        from pathlib import Path
        
        # Save original environment
        original_env = dict(os.environ)
        
        try:
            # Clear and load new environment
            os.environ.clear()
            
            if Path(env_file).exists():
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            if '=' in line:
                                key, value = line.split('=', 1)
                                os.environ[key.strip()] = value.strip()
            
            # Create config instance
            return cls()
        finally:
            # Restore original environment
            os.environ.clear()
            os.environ.update(original_env)
    
    def get_kernel_size_for_vram(self, vram_gb: float) -> int:
        """
        Get optimal kernel size based on available VRAM.
        Can be overridden with FORCE_KERNEL_SIZE environment variable.
        """
        import os

        # Check for manual override
        force_size = os.environ.get('FORCE_KERNEL_SIZE')
        if force_size:
            try:
                size = int(force_size)
                if size > 0:
                    return size
            except ValueError:
                pass

        # Auto-detect based on VRAM
        if vram_gb < 8:
            return self.KERNEL_SIZE_LOW_VRAM
        elif vram_gb < 16:
            return self.KERNEL_SIZE_MID_VRAM
        else:
            return self.KERNEL_SIZE_HIGH_VRAM


# Global configuration instance
_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Get or create configuration instance."""
    global _config
    if _config is None:
        _config = AppConfig()
    return _config
