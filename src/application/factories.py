"""Factory for creating processors."""

import os
from typing import Optional
from src.domain.protocols import IProcessor
from src.domain.exceptions import ProcessorNotAvailableError
from src.infrastructure.processors import RifePytorchWrapper, RealESRGANPytorchWrapper
from src.infrastructure.processors.subtitle import SubtitleRemoverWrapper
from src.shared.logging import get_logger

# Adapters
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_adapter import Sam2Adapter
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.infrastructure.inpainting.sttn_adapter import STTNAdapter
from src.services.masking.service import TextMaskService
from src.services.cleaner_service import SubtitleRemoverService
from src.core.config import get_config

logger = get_logger(__name__)


class ProcessorFactory:
    """
    Factory for creating video processors with auto-detection.
    """

    def __init__(self, use_native: Optional[bool] = None):
        self._logger = get_logger(__name__)

        if use_native is None:
            env_value = os.getenv('USE_NATIVE_PROCESSORS', '1')
            use_native = env_value == '1'

        self.use_native = use_native
        self._logger.info(f"Processor Factory initialized (native_mode={self.use_native})")

    def create_interpolator(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """Create interpolator (RIFE)."""
        # Native implementation preference
        if self.use_native or prefer == 'native':
            try:
                from src.infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
                if RIFENativeWrapper.is_available():
                    return RIFENativeWrapper()
            except ImportError:
                pass

        # Fallback to shell wrapper
        if RifePytorchWrapper.is_available():
            return RifePytorchWrapper()

        raise ProcessorNotAvailableError("No RIFE backend available")

    def create_subtitle_remover(self, prefer: str = 'auto', lang: str = 'en', backend: str = 'auto', roi: Optional[str] = None) -> Optional[IProcessor]:
        """
        Create subtitle removal processor.
        Integrates PaddleOCR + SAM2 + ProPainter-Wire.
        """
        if backend == 'auto' and prefer != 'auto':
            backend = prefer

        # Modern Pipeline (Default)
        if backend in ('sam2', 'auto'):
            try:
                self._logger.info("🚀 Initializing Modern Subtitle Pipeline (Paddle+SAM2+ProPainterWire)...")

                # 1. OCR (PaddleOCR)
                ocr = PaddleWrapper(lang=lang, use_gpu=True)

                # 2. Segmentation (SAM 2)
                sam2_ckpt = "/opt/sam2_checkpoints/sam2_hiera_small.pt"
                if not os.path.exists(sam2_ckpt):
                     self._logger.warning(f"SAM2 checkpoint not found at {sam2_ckpt}, checking ENV...")
                     # Можно добавить логику загрузки из ENV, если нужно

                sam2 = Sam2Adapter(checkpoint_path=sam2_ckpt)

                # 3. Mask Service
                mask_service = TextMaskService(ocr=ocr, sam2=sam2)

                # 4. Inpainter (ProPainter-Wire / LaMa)
                inpainter = self._create_inpainter()

                # 5. Debug Config
                debug_mode = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'

                # 6. Service Assembly
                return SubtitleRemoverService(
                    mask_service=mask_service,
                    inpainter=inpainter,
                    lang=lang,
                    roi_factor=roi,
                    debug=debug_mode
                )

            except Exception as e:
                self._logger.error(f"❌ Failed to initialize SAM2 pipeline: {e}")
                if backend == 'sam2':
                    raise ProcessorNotAvailableError(f"SAM2 pipeline critical failure: {e}")
                self._logger.warning("Falling back to legacy wrapper...")

        # Legacy Wrapper Fallback
        if SubtitleRemoverWrapper.is_available():
            return SubtitleRemoverWrapper(lang=lang, roi=roi)

        raise ProcessorNotAvailableError("Subtitle remover not available")

    def _create_inpainter(self):
        """Create inpainter adapter based on configuration."""
        config = get_config()
        engine = getattr(config, 'INPAINTING_ENGINE', 'propainter')

        if engine == "propainter":
            self._logger.info("🎨 Using ProPainter-Wire Adapter")
            # ProPainterAdapter теперь должен вызывать /opt/ProPainter-Wire
            return ProPainterAdapter()

        elif engine == "lama":
            self._logger.info("🖌️ Using LaMa Adapter")
            return LaMaAdapter()

        elif engine == "sttn":
            self._logger.info("📹 Using STTN Adapter")
            return STTNAdapter()

        else:
            self._logger.warning(f"Unknown engine '{engine}', defaulting to ProPainter")
            return ProPainterAdapter()

    def create_upscaler(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """Create upscaler (RealESRGAN)."""
        if self.use_native or prefer == 'native':
            try:
                from src.infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper
                if RealESRGANNativeWrapper.is_available():
                    return RealESRGANNativeWrapper()
            except ImportError:
                pass

        if RealESRGANPytorchWrapper.is_available():
            return RealESRGANPytorchWrapper()

        raise ProcessorNotAvailableError("No Real-ESRGAN backend available")

    def create_watermark_remover(self, roi: str = 'top-right', prefer: str = 'auto',
                               persistence_threshold: float = 0.8, expansion: int = 10) -> Optional[IProcessor]:
        """Create watermark remover."""
        try:
            from src.infrastructure.processors.watermark.wrapper import WatermarkRemoverWrapper
            if WatermarkRemoverWrapper.is_available():
                return WatermarkRemoverWrapper(
                    roi=roi,
                    static_detection=True,
                    persistence_threshold=persistence_threshold,
                    expansion=expansion
                )
        except ImportError:
            pass

        raise ProcessorNotAvailableError("Watermark remover not available")