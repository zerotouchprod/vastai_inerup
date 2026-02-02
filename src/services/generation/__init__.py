"""
Video generation module (Text-to-Video & Image-to-Video).

Provides isolated runtime for video generation with CogVideoX models.
"""

from .config import GenerationConfig
from .models import GenJob, GenerationResult, BatchGenerationResult, GenerationMode
from .orchestrator import GenerationOrchestrator

__all__ = [
    'GenerationConfig',
    'GenJob',
    'GenerationResult',
    'BatchGenerationResult',
    'GenerationMode',
    'GenerationOrchestrator',
]

# Lazy imports for engines (avoid loading diffusers until needed)
def __getattr__(name):
    if name == 'CogVideoText2VideoEngine':
        from .engines.text2video import CogVideoText2VideoEngine
        return CogVideoText2VideoEngine
    elif name == 'BaseVideoEngine':
        from .engines.base import BaseVideoEngine
        return BaseVideoEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
