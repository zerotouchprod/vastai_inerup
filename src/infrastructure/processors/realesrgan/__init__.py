"""Real-ESRGAN processors package."""

from infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper

try:
    from infrastructure.processors.realesrgan.pytorch_wrapper import RealESRGANPytorchWrapper
except Exception:  # pragma: no cover - defensive
    RealESRGANPytorchWrapper = None

__all__ = ["RealESRGANNativeWrapper", "RealESRGANPytorchWrapper"]
