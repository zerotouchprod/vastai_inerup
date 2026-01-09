"""Factory for creating processors."""

import os
from typing import Optional
from src.domain.protocols import IProcessor
from src.domain.exceptions import ProcessorNotAvailableError
from src.infrastructure.processors import RifePytorchWrapper, RealESRGANPytorchWrapper
from src.infrastructure.processors.subtitle import SubtitleRemoverWrapper
from src.shared.logging import get_logger

# New imports for SAM2 + OCR pipeline
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_adapter import Sam2Adapter
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.services.masking.service import TextMaskService
from src.services.cleaner_service import SubtitleRemoverService

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
                from src.infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
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

    def create_subtitle_remover(self, prefer: str = 'auto', lang: str = 'en', backend: str = 'auto', roi: Optional[str] = None) -> Optional[IProcessor]:
        """
        Create subtitle removal processor.

        Args:
            prefer: Backend preference ('auto', 'native', 'propainter') - deprecated, use backend parameter
            lang: Language code for OCR ('en', 'ru', etc.)
            backend: Backend preference ('auto', 'native', 'propainter', 'sam2')
            roi: Region of Interest string. "bottom" (default, 60%), "full" (100%), or float 0.0-1.0

        Returns:
            Subtitle remover processor instance

        Raises:
            GPURequiredError: If GPU is not available (required for subtitle removal)
        """
        # CRITICAL: Check GPU availability before creating any subtitle removal components
        from src.infrastructure.utils.gpu_utils import require_gpu
        require_gpu("subtitle removal")

        # Determine backend (prefer parameter for backward compatibility)
        if backend == 'auto' and prefer != 'auto':
            # If prefer is specified and backend is auto, use prefer
            backend = prefer
        
        # New SAM2 + OCR pipeline
        if backend in ('sam2', 'auto'):
            try:
                # 1. OCR
                ocr = PaddleWrapper(lang=lang, use_gpu=True)
                
                # 2. SAM 2
                # Путь к чекпоинту должен быть в конфиге или ENV
                sam2_ckpt = "/opt/sam2_checkpoints/sam2_hiera_small.pt"
                sam2 = Sam2Adapter(checkpoint_path=sam2_ckpt)
                
                # 3. Mask Service
                mask_service = TextMaskService(ocr=ocr, sam2=sam2)
                
                # 4. Inpainter
                inpainter = ProPainterAdapter()
                
                # 5. Debug mode detection
                import os
                debug_mode = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'

                # 6. Главный сервис
                return SubtitleRemoverService(mask_service, inpainter, lang=lang, roi_factor=roi, debug=debug_mode)
            except Exception as e:
                self._logger.warning(f"SAM2 pipeline failed to initialize: {e}")
                if backend == 'sam2':
                    raise ProcessorNotAvailableError(f"SAM2 pipeline not available: {e}")
                # Fall through to old backend if auto
        
        # Check for old subtitle remover backend (for backward compatibility)
        if backend in ('auto', 'propainter', 'native'):  # native тоже перенаправляем на ProPainter
            if SubtitleRemoverWrapper.is_available():
                self._logger.info(f"Using legacy subtitle remover backend (lang={lang}, roi={roi})")
                # Pass roi parameter to wrapper
                return SubtitleRemoverWrapper(lang=lang, roi=roi)
            else:
                raise ProcessorNotAvailableError("Subtitle remover not available (requires ProPainter installation in /opt/ProPainter)")
        
        raise ProcessorNotAvailableError(f"Unknown backend: {backend}")

    def create_watermark_remover(self,
                                 roi: str = 'top-right',
                                 prefer: str = 'auto',
                                 persistence_threshold: float = 0.8,
                                 expansion: int = 10) -> Optional[IProcessor]:
        """
        Create watermark removal processor.

        Args:
            roi: ROI string (single or multi: "top-right,bottom-left")
            prefer: Backend preference (currently only 'auto' supported)
            persistence_threshold: Ratio of frames a pixel must appear in (0.0-1.0)
            expansion: Mask expansion radius in pixels

        Returns:
            Watermark remover processor instance

        Raises:
            GPURequiredError: If GPU is not available (required for watermark removal)
        """
        # CRITICAL: Check GPU availability before creating watermark removal components
        from src.infrastructure.utils.gpu_utils import require_gpu
        require_gpu("watermark removal")

        try:
            from src.infrastructure.processors.watermark.wrapper import WatermarkRemoverWrapper

            if WatermarkRemoverWrapper.is_available():
                self._logger.info(f"Creating watermark remover (roi={roi}, persistence={persistence_threshold})")
                return WatermarkRemoverWrapper(
                    roi=roi,
                    static_detection=True,
                    persistence_threshold=persistence_threshold,
                    expansion=expansion
                )
            else:
                raise ProcessorNotAvailableError(
                    "Watermark remover not available (requires ProPainter installation in /opt/ProPainter)"
                )
        except ImportError as e:
            raise ProcessorNotAvailableError(f"Watermark remover dependencies not found: {e}")

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
                from src.infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper
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
