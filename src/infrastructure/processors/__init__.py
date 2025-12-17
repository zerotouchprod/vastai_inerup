"""Processors package."""

from .base import BaseProcessor

# Try to import optional wrappers (may be absent in some working copies)
try:
    from .rife import RifePytorchWrapper
except Exception:  # pragma: no cover - defensive
    RifePytorchWrapper = None

try:
    from .realesrgan import RealESRGANPytorchWrapper
except Exception:  # pragma: no cover - defensive
    RealESRGANPytorchWrapper = None

__all__ = [
    "BaseProcessor",
    "RifePytorchWrapper",
    "RealESRGANPytorchWrapper",
]
