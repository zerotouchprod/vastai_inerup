"""Factory for creating processors."""

from typing import Optional
from domain.protocols import IProcessor
from domain.exceptions import ProcessorNotAvailableError
from infrastructure.processors import RifePytorchWrapper, RealESRGANPytorchWrapper
from shared.logging import get_logger

logger = get_logger(__name__)


class ProcessorFactory:
    """Factory for creating video processors with auto-detection."""

    def __init__(self):
        self._logger = get_logger(__name__)

    def create_interpolator(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """Create interpolator processor."""
        if prefer == 'auto':
            if RifePytorchWrapper.is_available():
                self._logger.info("Using RIFE pytorch backend")
                return RifePytorchWrapper()
            raise ProcessorNotAvailableError("No RIFE backend available")

        elif prefer == 'pytorch':
            if RifePytorchWrapper.is_available():
                return RifePytorchWrapper()
            raise ProcessorNotAvailableError("RIFE pytorch not available")

        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")

    def create_upscaler(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """Create upscaler processor."""
        if prefer == 'auto':
            if RealESRGANPytorchWrapper.is_available():
                self._logger.info("Using Real-ESRGAN pytorch backend")
                return RealESRGANPytorchWrapper()
            raise ProcessorNotAvailableError("No Real-ESRGAN backend available")

        elif prefer == 'pytorch':
            if RealESRGANPytorchWrapper.is_available():
                return RealESRGANPytorchWrapper()
            raise ProcessorNotAvailableError("Real-ESRGAN pytorch not available")

        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")
