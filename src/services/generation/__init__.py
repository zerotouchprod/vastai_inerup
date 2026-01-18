"""
Text-to-Video generation module.

This module provides functionality for generating videos from text prompts
using diffusion models like CogVideoX-5b.

Note: Importing CogVideoEngine requires diffusers and torch.
"""

from .config import GenerationConfig
from .models import GenJob

__all__ = [
    'GenerationConfig',
    'GenJob',
]

# Lazy imports to avoid requiring diffusers/torch at module level
def __getattr__(name):
    if name == 'CogVideoEngine':
        from .engine import CogVideoEngine
        return CogVideoEngine
    elif name == 'GenerationOrchestrator':
        from .orchestrator import GenerationOrchestrator
        return GenerationOrchestrator
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
