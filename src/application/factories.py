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

    def _inject_pure_pytorch_corrblock(self):
        """
        Inject Pure PyTorch CorrBlock into ProPainter's RAFT module.

        ProPainter's RAFT imports CorrBlock from spatial_correlation_sampler:
            from .corr import CorrBlock

        But we replaced spatial_correlation_sampler with Pure PyTorch version.
        This method monkey-patches ProPainter's RAFT to use our implementation.

        Architecture:
        - ProPainter/RAFT expects: from .corr import CorrBlock
        - We inject: sys.modules['/opt/ProPainter/RAFT/corr'].CorrBlock = our_CorrBlock
        - RAFT imports our version seamlessly

        Design pattern: Dependency injection via module monkey-patching
        """
        import sys
        from pathlib import Path

        try:
            # 1. Install pure PyTorch correlation (if not already)
            from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock as PurePytorchCorrBlock

            # 2. Add ProPainter to sys.path if needed
            propainter_root = Path("/opt/ProPainter")
            if str(propainter_root) not in sys.path:
                sys.path.insert(0, str(propainter_root))

            # 3. Create fake 'corr' module with our CorrBlock
            class FakeCorrModule:
                """Fake module that provides Pure PyTorch CorrBlock."""
                CorrBlock = PurePytorchCorrBlock

            # 4. Inject into ProPainter's RAFT namespace
            # ProPainter does: from .corr import CorrBlock
            # We make .corr point to our fake module
            raft_module_name = 'RAFT.corr'
            sys.modules[raft_module_name] = FakeCorrModule()

            self._logger.info("✅ Injected Pure PyTorch CorrBlock into ProPainter RAFT")
            self._logger.info("   ProPainter will use Pure PyTorch correlation (no C++ extension)")

        except Exception as e:
            self._logger.error(f"❌ Failed to inject Pure PyTorch CorrBlock: {e}")
            self._logger.error("   ProPainter may fail if it tries to use spatial-correlation-sampler")
            # Don't raise - let ProPainter try anyway, it will give clearer error

    def _validate_corrblock_injection(self) -> bool:
        """
        Validate that CorrBlock injection succeeded and ProPainter RAFT can use it.

        This is a critical pre-flight check that prevents the error:
            File "/opt/ProPainter/RAFT/raft.py", line 109, in forward
                corr_fn = CorrBlock

        Design pattern: Fail-fast validation

        Returns:
            bool: True if validation passed

        Raises:
            RuntimeError: If CorrBlock injection failed and ProPainter will crash
        """
        import sys
        from pathlib import Path

        try:
            # Check 1: Verify injection happened
            if 'RAFT.corr' not in sys.modules:
                raise RuntimeError(
                    "CorrBlock injection failed: 'RAFT.corr' module not found in sys.modules.\n"
                    "ProPainter RAFT will crash with 'corr_fn = CorrBlock' error."
                )

            # Check 2: Verify module has CorrBlock
            corr_module = sys.modules['RAFT.corr']
            if not hasattr(corr_module, 'CorrBlock'):
                raise RuntimeError(
                    "CorrBlock injection incomplete: 'RAFT.corr' module exists but has no CorrBlock.\n"
                    "ProPainter RAFT will crash with 'corr_fn = CorrBlock' error."
                )

            # Check 3: Try to import from ProPainter's perspective
            propainter_root = Path("/opt/ProPainter")
            if str(propainter_root) not in sys.path:
                sys.path.insert(0, str(propainter_root))

            # Simulate what ProPainter RAFT does
            try:
                # This is what RAFT/raft.py line 109 tries to do
                from RAFT.corr import CorrBlock

                # Verify it's our Pure PyTorch version
                from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock as OurCorrBlock
                if CorrBlock is not OurCorrBlock:
                    self._logger.warning(
                        "⚠️  CorrBlock imported but it's not our Pure PyTorch version!\n"
                        "   This may cause issues. Expected Pure PyTorch, got something else."
                    )
                else:
                    self._logger.info("✅ CorrBlock validation passed: ProPainter will use Pure PyTorch")

                return True

            except ImportError as e:
                raise RuntimeError(
                    f"CorrBlock injection failed: Cannot import 'from RAFT.corr import CorrBlock'\n"
                    f"Error: {e}\n"
                    f"ProPainter RAFT will crash with 'corr_fn = CorrBlock' error."
                )

        except RuntimeError:
            raise  # Re-raise validation errors
        except Exception as e:
            # Unexpected error during validation
            self._logger.error(f"❌ Unexpected error during CorrBlock validation: {e}")
            raise RuntimeError(
                f"CorrBlock validation failed with unexpected error: {e}\n"
                f"ProPainter may not work correctly."
            )

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

        Note:
            GPU is required for subtitle removal, but not explicitly checked here.
            If GPU is missing, PaddleOCR/SAM2 will fail with clear error messages.
        """
        # Note: GPU check removed - it was causing false negatives when torch
        # imports before pure PyTorch correlation is installed. PaddleOCR/SAM2
        # will validate GPU when they actually need it.

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
                
                # 4. Inject Pure PyTorch CorrBlock into ProPainter RAFT (CRITICAL!)
                # ProPainter's RAFT tries to import CorrBlock from spatial_correlation_sampler
                # But we replaced it with Pure PyTorch version, so we need to inject it
                self._inject_pure_pytorch_corrblock()

                # 5. Validate CorrBlock injection
                self._validate_corrblock_injection()

                # 6. Inpainter
                inpainter = ProPainterAdapter()
                
                # 7. Debug mode detection
                import os
                debug_mode = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'

                # 8. Главный сервис
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

        Note:
            GPU is required for watermark removal, but not explicitly checked here.
            If GPU is missing, ProPainter/inpainting will fail with clear error messages.
        """
        # Note: GPU check removed - same reason as subtitle remover
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
