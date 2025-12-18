"""Infrastructure layer package."""

# Import only existing modules
try:
    from src.infrastructure.config import ConfigLoader, ProcessingConfig
except ImportError:
    pass

try:
    from src.infrastructure.io import HttpDownloader, B2S3Uploader
except ImportError:
    pass

try:
    from src.infrastructure.media import FFmpegWrapper, FFmpegExtractor, FFmpegAssembler
except ImportError:
    pass

try:
    from src.infrastructure.processors import BaseProcessor, RifePytorchWrapper, RealESRGANPytorchWrapper
except ImportError:
    pass

# New modules (may not be imported by old code)
try:
    from src.infrastructure.vastai.client import VastAIClient
except ImportError:
    pass

try:
    from src.infrastructure.storage.b2_client import B2Client
except ImportError:
    pass

__all__ = [
    # Keep for backward compatibility, but don't fail if missing
]
