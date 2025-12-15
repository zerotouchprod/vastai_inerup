"""Factory for creating processors."""

import os
from typing import Optional
from domain.protocols import IProcessor
from domain.exceptions import ProcessorNotAvailableError
from infrastructure.processors import RifePytorchWrapper, RealESRGANPytorchWrapper
from infrastructure.processors.subtitle import SubtitleRemoverWrapper
from shared.logging import get_logger

logger = get_logger(__name__)


class ProcessorFactory:
    """
    Factory for creating video processors with auto-detection.

    Supports both shell-based wrappers (default) and native Python implementations.

    Use native implementations for:
    - Better debugging (step-by-step in PyCharm)
    - No shell dependencies
    - Cleaner code

    Enable with:
        factory = ProcessorFactory(use_native=True)
        # or
        export USE_NATIVE_PROCESSORS=1
    """

    def __init__(self, use_native: Optional[bool] = None):
        """
        Initialize factory.

        Args:
            use_native: Use native Python implementations instead of shell wrappers.
                       If None, reads from USE_NATIVE_PROCESSORS env var.
        """
        self._logger = get_logger(__name__)

        # Determine whether to use native implementations
        # Default to '1' (native) for better debugging and pure Python code
        if use_native is None:
            env_value = os.getenv('USE_NATIVE_PROCESSORS', '1')
            use_native = env_value == '1'
            self._logger.debug(f"USE_NATIVE_PROCESSORS env={env_value}, use_native={use_native}")

        self.use_native = use_native

        if self.use_native:
            self._logger.info("[NATIVE] Using NATIVE Python processors (no shell scripts)")
        else:
            self._logger.info("[SHELL] Using shell-wrapped processors (default)")

    def create_interpolator(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """
        Create interpolator processor.

        Args:
            prefer: Backend preference ('auto', 'pytorch', 'native')

        Returns:
            Interpolator processor instance
        """
        # If native implementations requested, try native first
        if self.use_native or prefer == 'native':
            try:
                from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
                if RIFENativeWrapper.is_available():
                    self._logger.info("Using RIFE native Python backend")
                    return RIFENativeWrapper()
                else:
                    self._logger.warning("RIFE native is not available (is_available=False), falling back to shell wrapper")
            except ImportError as e:
                self._logger.warning(f"RIFE native import failed: {e}, falling back to shell wrapper")
                if prefer == 'native':
                    raise ProcessorNotAvailableError("RIFE native not available")
                # Fall through to shell wrapper if not explicitly native

        # Shell wrapper (default)
        if prefer in ('auto', 'pytorch'):
            if RifePytorchWrapper and getattr(RifePytorchWrapper, 'is_available', lambda: False)():
                self._logger.info("Using RIFE pytorch backend (shell wrapper)")
                return RifePytorchWrapper()
            raise ProcessorNotAvailableError("No RIFE backend available")


        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")

    def create_subtitle_remover(self, prefer: str = 'auto', lang: str = 'en') -> Optional[IProcessor]:
        """
        Create subtitle removal processor.

        Args:
            prefer: Backend preference ('auto', 'native')
            lang: Language code for OCR ('en', 'ru', etc.)

        Returns:
            Subtitle remover processor instance
        """
        # Currently only native implementation exists
        if prefer in ('auto', 'native'):
            if SubtitleRemoverWrapper.is_available():
                self._logger.info(f"Using subtitle remover native backend (lang={lang})")
                return SubtitleRemoverWrapper(lang=lang)
            raise ProcessorNotAvailableError("Subtitle remover not available (requires paddleocr, opencv)")
        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")

    def create_upscaler(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """
        Create upscaler processor.

        Args:
            prefer: Backend preference ('auto', 'pytorch', 'native')

        Returns:
            Upscaler processor instance
        """
        # If native implementations requested, try native first
        if self.use_native or prefer == 'native':
            try:
                from infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper
                if RealESRGANNativeWrapper.is_available():
                    self._logger.info("Using Real-ESRGAN native Python backend")
                    return RealESRGANNativeWrapper()
                else:
                    self._logger.warning("Real-ESRGAN native is not available (is_available=False), falling back to shell wrapper")
            except ImportError as e:
                self._logger.warning(f"Real-ESRGAN native import failed: {e}, falling back to shell wrapper")
                if prefer == 'native':
                    raise ProcessorNotAvailableError("Real-ESRGAN native not available")
                # Fall through to shell wrapper if not explicitly native

        # Shell wrapper (default)
        if prefer in ('auto', 'pytorch'):
            if RealESRGANPytorchWrapper and getattr(RealESRGANPytorchWrapper, 'is_available', lambda: False)():
                self._logger.info("Using Real-ESRGAN pytorch backend (shell wrapper)")
                return RealESRGANPytorchWrapper()
            raise ProcessorNotAvailableError("No Real-ESRGAN backend available")


        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")
