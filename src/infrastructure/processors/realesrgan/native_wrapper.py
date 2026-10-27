"""
Wrapper adapter for native Python Real-ESRGAN implementation.

This adapter uses the pure Python implementation instead of shell scripts.
"""

import os
from pathlib import Path
from typing import List, Dict, Any

from src.infrastructure.processors.base import BaseProcessor
from src.infrastructure.processors.realesrgan.native import get_upscaler
from src.domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from src.shared.logging import get_logger

logger = get_logger(__name__)


class RealESRGANNativeWrapper(BaseProcessor):
    """
    Adapter for native Python Real-ESRGAN implementation.

    No shell scripts - pure Python with full debugging support!
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.is_available():
            raise ProcessorNotAvailableError("Real-ESRGAN dependencies not available")

        # Create native processor (will be configured in _execute_processing)
        self._processor = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if Real-ESRGAN dependencies are available."""
        try:
            import torch

            logger.info(f"[DEBUG] PyTorch version: {torch.__version__}")
            logger.info(f"[DEBUG] CUDA available: {torch.cuda.is_available()}")
            if torch.cuda.is_available():
                logger.info(f"[DEBUG] CUDA device: {torch.cuda.get_device_name(0)}")
                logger.info(
                    f"[DEBUG] CUDA capability: {torch.cuda.get_device_capability(0)}"
                )
            # Note: CUDA is preferred but not required for testing
            # The actual device selection happens during model loading

            from basicsr.archs.rrdbnet_arch import RRDBNet  # noqa: F401

            logger.info("[DEBUG] basicsr.archs.rrdbnet_arch import OK")

            from realesrgan import RealESRGANer  # noqa: F401

            logger.info("[DEBUG] realesrgan import OK")

            logger.info("Real-ESRGAN native is available (all dependencies found)")
            return True
        except ImportError as e:
            logger.warning(f"Real-ESRGAN native not available - ImportError: {e}")
            import traceback

            logger.warning(f"Import traceback: {traceback.format_exc()}")
            return False
        except Exception as e:
            logger.warning(f"Real-ESRGAN native availability check failed: {e}")
            import traceback

            logger.warning(f"Exception traceback: {traceback.format_exc()}")
            return False

    def supports_gpu(self) -> bool:
        """Native implementation uses GPU."""
        return True

    def _execute_processing(
        self, input_frames: List[Path], output_dir: Path, options: Dict[str, Any]
    ) -> List[Path]:
        """
        Execute Real-ESRGAN upscaling using native Python.

        Args:
            input_frames: Input frame paths
            output_dir: Output directory
            options: Processing options

        Returns:
            List of upscaled frame paths
        """
        # Get options
        scale = int(options.get("scale", 2))
        model_name_override = options.get("model_name") or os.getenv(
            "REAL_ESRGAN_MODEL_X2" if scale == 2 else "REAL_ESRGAN_MODEL_X4"
        )
        tile_size = options.get("tile_size") if "tile_size" in options else None
        if tile_size is None and os.getenv("REAL_ESRGAN_TILE_SIZE"):
            tile_size = int(os.environ["REAL_ESRGAN_TILE_SIZE"])
        batch_size = options.get("batch_size")  # None = resolution-aware auto-detect
        if batch_size is None and os.getenv("REAL_ESRGAN_BATCH_SIZE"):
            batch_size = int(os.environ["REAL_ESRGAN_BATCH_SIZE"])
        half = options.get("half", os.getenv("REAL_ESRGAN_HALF", "true").lower() not in ("0", "false", "no"))
        device = options.get("device", "cuda")
        is_intermediate = options.get("_intermediate_stage", False)

        if is_intermediate:
            self._logger.info(
                f"Running Real-ESRGAN (Native Python, intermediate stage): scale={scale}"
            )
        else:
            self._logger.info(f"Running Real-ESRGAN (Native Python): scale={scale}")

        try:
            get_args = (scale, half, device, tile_size, batch_size)
            get_kwargs: Dict[str, Any] = {"logger": self._logger}
            if model_name_override:
                get_kwargs["model_name"] = model_name_override
            self._processor = get_upscaler(*get_args, **get_kwargs)

            output_frames = self._processor.process_frames(
                input_frames,
                output_dir,
                progress_callback=options.get("progress_callback"),
                cancel_event=options.get("cancel_event"),
            )

            if not output_frames:
                raise VideoProcessingError("No output frames produced")

            # Note: Native processors don't handle B2 uploads
            # The orchestrator will upload the final assembled video
            if is_intermediate:
                self._logger.debug(
                    "Intermediate stage - orchestrator will handle final upload"
                )

            return output_frames

        except Exception as e:
            error_msg = f"Native Real-ESRGAN processing failed: {e}"
            self._logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e
