import os
import sys
from pathlib import Path

# Add current directory to Python path for imports
sys.path.insert(0, '/app/src')

from typing import Optional
from src.domain.protocols import IProcessor
from src.domain.exceptions import ProcessorNotAvailableError
from src.shared.logging import get_logger

logger = get_logger(__name__)

# Global placeholder for missing classes
RifeWrapper = None
RealESRGANPytorchWrapper = None
RIFENativeWrapper = None
RealESRGANNativeWrapper = None
IFENativeWrapper = None


# Safe import functions with graceful fallback
def safe_import(module_path, class_name):
    """Safely import a class with fallback to None."""
    try:
        module = __import__(module_path, fromlist=[class_name])
        cls = getattr(module, class_name)
        logger.info(f"✅ Successfully imported {class_name} from {module_path}")
        return cls
    except ImportError as e:
        logger.warning(f"⚠️ Could not import {class_name} from {module_path}: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected error importing {class_name} from {module_path}: {e}")
        return None


# Import heavy processing classes with safe imports
RifeWrapper = safe_import('src.infrastructure.processors.rife.native_wrapper', 'RIFENativeWrapper')
RealESRGANPytorchWrapper = safe_import('src.infrastructure.processors.realesrgan.native_wrapper',
                                       'RealESRGANPytorchWrapper')
RIFENativeWrapper = safe_import('src.infrastructure.processors.rife.native_wrapper', 'RIFENativeWrapper')
RealESRGANNativeWrapper = safe_import('src.infrastructure.processors.realesrgan.native_wrapper',
                                      'RealESRGANNativeWrapper')
IFENativeWrapper = safe_import('src.infrastructure.processors.rife.native_wrapper', 'IFENativeWrapper')

# Import lightweight classes normally
from src.infrastructure.processors.subtitle.wrapper import SubtitleRemoverWrapper
from src.infrastructure.processors.watermark.wrapper import WatermarkRemoverWrapper
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_adapter import Sam2Adapter
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

# Import service classes
from src.services.masking.service import TextMaskService
from src.services.cleaner_service import SubtitleRemoverService
from src.services.watermark_service import WatermarkRemoverService


class ProcessorFactory:
    def __init__(self, use_native: Optional[bool] = None):
        """
        Initialize factory with graceful dependency handling.
        """
        self._logger = get_logger(__name__)

        # Determine whether to use native implementations
        if use_native is None:
            use_native = os.getenv('USE_NATIVE_PROCESSORS', '1') == '1'

        self._logger.info(f"🔧 ProcessorFactory initialized (native={use_native})")
        self._logger.info(
            f"📊 Available modules: RIFE={RifeWrapper is not None}, RealESRGAN={RealESRGANPytorchWrapper is not None}")

    def _safe_create_rife(self, prefer: str):
        """Safely create RIFE processor with fallback."""
        if prefer == 'pytorch' and RifeWrapper:
            self._logger.info("✅ Using RIFE PyTorch backend")
            return RifeWrapper()
        elif prefer == 'native' and RIFENativeWrapper:
            self._logger.info("✅ Using RIFE native backend")
            return RIFENativeWrapper()
        elif RifeWrapper:
            self._logger.info("✅ Using RIFE fallback backend")
            return RifeWrapper()
        else:
            self._logger.warning("⚠️ RIFE not available, processor will be None")
            return None

    def _safe_create_realesrgan(self, prefer: str):
        """Safely create Real-ESRGAN processor with fallback."""
        if prefer == 'pytorch' and RealESRGANPytorchWrapper:
            self._logger.info("✅ Using Real-ESRGAN PyTorch backend")
            return RealESRGANPytorchWrapper()
        elif prefer == 'native' and RealESRGANNativeWrapper:
            self._logger.info("✅ Using Real-ESRGAN native backend")
            return RealESRGANNativeWrapper()
        elif RealESRGANPytorchWrapper:
            self._logger.info("✅ Using Real-ESRGAN fallback backend")
            return RealESRGANPytorchWrapper()
        else:
            self._logger.warning("⚠️ Real-ESRGAN not available, processor will be None")
            return None

    def create_upscaler(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """
        Create upscaler processor with graceful fallback.
        """
        self._logger.info(f"🔧 Creating upscaler (prefer={prefer})")

        if prefer == 'rife':
            return self._safe_create_rife('pytorch')
        elif prefer == 'realesrgan':
            return self._safe_create_realesrgan('pytorch')
        elif prefer in ('pytorch', 'auto'):
            rife_result = self._safe_create_rife('pytorch')
            if rife_result:
                return rife_result
            realesrgan_result = self._safe_create_realesrgan('pytorch')
            if realesrgan_result:
                return realesrgan_result
        elif prefer in ('native', 'auto'):
            rife_native = self._safe_create_rife('native')
            if rife_native:
                return rife_native
            realesrgan_native = self._safe_create_realesrgan('native')
            if realesrgan_native:
                return realesrgan_native

        self._logger.warning("⚠️ No upscaler backends available")
        return None

    def create_subtitle_remover(self,
                                lang: str = 'en',
                                roi: str = 'bottom',
                                backend: str = 'auto',
                                animated: bool = False) -> Optional[IProcessor]:
        """
        Create subtitle remover processor with graceful fallback.
        """
        self._logger.info(
            f"🔧 Creating subtitle remover (lang={lang}, roi={roi}, backend={backend}, animated={animated})")

        if backend in ('auto', 'propainter', 'native'):
            # Try to use ProPainter wrapper (v2.1)
            try:
                # Check if ProPainter is available
                propainter_root = Path(os.getenv('PROPAINTER_ROOT', '/opt/ProPainter'))
                propainter_available = propainter_root.exists() and propainter_root.join('ProPainter.pth').exists()

                if propainter_available:
                    self._logger.info("✅ Using ProPainter backend for subtitle removal")
                    if animated:
                        # Try to use animated text detection (v2.1)
                        from src.infrastructure.processors.subtitle.animated_wrapper import \
                            SubtitleRemoverAnimatedWrapper
                        try:
                            animated_wrapper = SubtitleRemoverAnimatedWrapper()
                            self._logger.info("✅ Using ProPainter + Animated Text Detection backend")
                            return animated_wrapper
                        except ImportError:
                            self._logger.warning(
                                "⚠️ Animated wrapper not available, falling back to standard ProPainter")
                    else:
                        return SubtitleRemoverWrapper(lang=lang, roi=roi)
                else:
                    self._logger.warning("⚠️ ProPainter not available, falling back to legacy wrapper")
            except Exception as e:
                self._logger.error(f"❌ Error creating ProPainter wrapper: {e}")
                raise ProcessorNotAvailableError(
                    "Subtitle remover not available (requires ProPainter installation in /opt/ProPainter)")
        else:
            raise ProcessorNotAvailableError(f"Unknown backend: {backend}")

    def create_watermark_remover(self,
                                 roi: str = 'top-right',
                                 prefer: str = 'auto',
                                 persistence_threshold: float = 0.8,
                                 expansion: int = 10) -> Optional[IProcessor]:
        """
        Create watermark remover processor.
        """
        self._logger.info(f"🔧 Creating watermark remover (roi={roi})")

        try:
            return WatermarkRemoverWrapper(
                roi=roi,
                persistence_threshold=persistence_threshold,
                expansion=expansion
            )
        except Exception as e:
            raise ProcessorNotAvailableError(f"Watermark remover dependencies not found: {e}")

    def create_sam2_processor(self) -> Optional[IProcessor]:
        """
        Create SAM2 processor with graceful fallback.
        """
        self._logger.info("🔧 Creating SAM2 processor")

        try:
            ocr_available = PaddleWrapper.is_available()
            if ocr_available:
                self._logger.info("✅ Using SAM2 + PaddleOCR backend")
                return Sam2Adapter()
            else:
                self._logger.warning("⚠️ SAM2 fallback: EasyOCR not installed, processor will be None")
                return None
        except Exception as e:
            self._logger.error(f"❌ Error creating SAM2 processor: {e}")
            return None

    def create_text_mask_service(self) -> Optional[TextMaskService]:
        """
        Create text mask service.
        """
        self._logger.info("🔧 Creating text mask service")

        try:
            ocr_wrapper = PaddleWrapper(lang='en', use_gpu=False)
            return TextMaskService(ocr_wrapper)
        except Exception as e:
            self._logger.error(f"❌ Error creating text mask service: {e}")
            return None

    def create_subtitle_remover_service(self) -> Optional[SubtitleRemoverService]:
        """
        Create subtitle remover service.
        """
        self._logger.info("🔧 Creating subtitle remover service")

        try:
            mask_service = self.create_text_mask_service()
            if mask_service:
                return SubtitleRemoverService(mask_service)
            else:
                self._logger.error("❌ Cannot create subtitle remover service without mask service")
                return None
        except Exception as e:
            self._logger.error(f"❌ Error creating subtitle remover service: {e}")
            return None

    def create_watermark_remover_service(self) -> Optional[WatermarkRemoverService]:
        """
        Create watermark remover service.
        """
        self._logger.info("🔧 Creating watermark remover service")

        try:
            return WatermarkRemoverService()
        except Exception as e:
            self._logger.error(f"❌ Error creating watermark remover service: {e}")
            return None
