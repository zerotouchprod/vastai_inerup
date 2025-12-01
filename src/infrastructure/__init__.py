"""Infrastructure layer package."""

# Import only existing modules
try:
    from infrastructure.config import ConfigLoader, ProcessingConfig
except ImportError:
    pass

try:
    from infrastructure.io import HttpDownloader, B2S3Uploader
except ImportError:
    pass

try:
    from infrastructure.media import FFmpegWrapper, FFmpegExtractor, FFmpegAssembler
except ImportError:
    pass

try:
    from infrastructure.processors import BaseProcessor, RifePytorchWrapper, RealESRGANPytorchWrapper
except ImportError:
    pass

# New modules (may not be imported by old code)
try:
    from infrastructure.vastai.client import VastAIClient
except ImportError:
    pass

try:
    from infrastructure.storage.b2_client import B2Client
except ImportError:
    pass

__all__ = [
    # Keep for backward compatibility, but don't fail if missing
]
