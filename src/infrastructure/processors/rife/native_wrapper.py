"""
Wrapper adapter for native Python RIFE implementation.

This adapter uses the pure Python implementation instead of shell scripts.
"""

from pathlib import Path
from typing import List, Dict, Any, TYPE_CHECKING

from infrastructure.processors.base import BaseProcessor
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

if TYPE_CHECKING:
    from infrastructure.processors.rife.native import RIFENative

logger = get_logger(__name__)


class RIFENativeWrapper(BaseProcessor):
    """
    Adapter for native Python RIFE implementation.

    No shell scripts - pure Python with full debugging support!
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.is_available():
            raise ProcessorNotAvailableError("RIFE dependencies not available")

        # Create native processor (will be configured in _execute_processing)
        self._processor = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if RIFE dependencies are available."""
        try:
            import torch
            
            # Check CUDA availability
            if not torch.cuda.is_available():
                logger.debug("RIFE native not available: CUDA not available")
                return False

            # Check that we can import the native module (don't instantiate yet)
            from infrastructure.processors.rife.native import RIFENative

            # Basic availability check - actual model loading happens in _execute_processing
            logger.debug("RIFE native is available (PyTorch + CUDA detected)")
            return True
        except ImportError as e:
            logger.debug(f"RIFE native not available: {e}")
            return False
        except Exception as e:
            logger.debug(f"RIFE native availability check failed: {e}")
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
        Execute RIFE interpolation using native Python.

        Args:
            input_frames: Input frame paths
            output_dir: Output directory
            options: Processing options

        Returns:
            List of interpolated frame paths
        """
        # Get options
        factor = options.get('factor', 2.0)
        is_intermediate = options.get('_intermediate_stage', False)

        if is_intermediate:
            self._logger.info(f"Running RIFE (Native Python, intermediate stage): factor={factor}")
        else:
            self._logger.info(f"Running RIFE (Native Python): factor={factor}")

        try:
            # Create processor if not exists
            if self._processor is None:
                self._processor = RIFENative(
                    factor=factor,
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

            # Note: Native processors don't handle B2 uploads
            # The orchestrator will upload the final assembled video
            if is_intermediate:
                self._logger.debug("Intermediate stage - orchestrator will handle final upload")

            return output_frames

        except Exception as e:
            error_msg = f"Native RIFE processing failed: {e}"
            self._logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

