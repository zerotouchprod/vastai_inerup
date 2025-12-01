"""
Wrapper adapter for native Python Real-ESRGAN implementation.

This adapter uses the pure Python implementation instead of shell scripts.
"""

from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from infrastructure.processors.realesrgan.native import RealESRGANNative
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

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
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
            return torch.cuda.is_available()
        except ImportError:
            return False

    def supports_gpu(self) -> bool:
        """Native implementation uses GPU."""
        return True

    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
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
        scale = options.get('scale', 2)
        tile_size = options.get('tile_size', 512)
        batch_size = options.get('batch_size')  # None = auto-detect
        half = options.get('half', True)

        self._logger.info(f"Running Real-ESRGAN (Native Python): scale={scale}")

        try:
            # Create processor if not exists
            if self._processor is None:
                self._processor = RealESRGANNative(
                    scale=scale,
                    tile_size=tile_size,
                    batch_size=batch_size,
                    half=half,
                    logger=self._logger
                )

            # Process frames
            output_frames = self._processor.process_frames(
                input_frames,
                output_dir,
                progress_callback=None  # TODO: Add progress tracking
            )

            if not output_frames:
                raise VideoProcessingError("No output frames produced")

            return output_frames

        except Exception as e:
            error_msg = f"Native Real-ESRGAN processing failed: {e}"
            self._logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

