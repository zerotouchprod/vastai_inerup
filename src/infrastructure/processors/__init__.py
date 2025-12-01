"""Processors package."""

from infrastructure.processors.base import BaseProcessor
from infrastructure.processors.rife import RifePytorchWrapper
from infrastructure.processors.realesrgan import RealESRGANPytorchWrapper

__all__ = [
    "BaseProcessor",
    "RifePytorchWrapper",
    "RealESRGANPytorchWrapper",
]

