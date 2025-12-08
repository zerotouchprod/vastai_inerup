"""Processors package."""

from infrastructure.processors.base import BaseProcessor

# Try to import optional wrappers (may be absent in some working copies)
try:
    from infrastructure.processors.rife import RifePytorchWrapper
except Exception:  # pragma: no cover - defensive
    RifePytorchWrapper = None

try:
    from infrastructure.processors.realesrgan import RealESRGANPytorchWrapper
except Exception:  # pragma: no cover - defensive
    RealESRGANPytorchWrapper = None

__all__ = [
    "BaseProcessor",
    "RifePytorchWrapper",
    "RealESRGANPytorchWrapper",
]
