"""Real-ESRGAN PyTorch wrapper adapter."""

import subprocess
import os
from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

logger = get_logger(__name__)


class RealESRGANPytorchWrapper(BaseProcessor):
    """
    Adapter for PyTorch Real-ESRGAN implementation.
    Wraps the existing run_realesrgan_pytorch.sh script.
    """

    WRAPPER_SCRIPT = Path("/workspace/project/run_realesrgan_pytorch.sh")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.is_available():
            raise ProcessorNotAvailableError("Real-ESRGAN PyTorch wrapper is not available")

    @classmethod
    def is_available(cls) -> bool:
        """Check if PyTorch and CUDA are available."""
        try:
            # Check if wrapper script exists
            if not cls.WRAPPER_SCRIPT.exists():
                return False

            # Check if PyTorch with CUDA is available
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def supports_gpu(self) -> bool:
        """Real-ESRGAN PyTorch uses GPU."""
        return True

    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
    ) -> List[Path]:
        """
        Execute Real-ESRGAN upscaling via wrapper script.

        Args:
            input_frames: Input frame paths
            output_dir: Output directory
            options: Processing options (scale, etc.)

        Returns:
            List of upscaled frame paths

        Raises:
            VideoProcessingError: If processing fails
        """
        # Get options
        scale = options.get('scale', 2)
        timeout = options.get('timeout', 7200)  # 2 hours for upscaling

        # Input/output paths
        input_dir = input_frames[0].parent
        temp_output_video = output_dir / "upscaled_temp.mp4"

        # Build command
        cmd = [
            str(self.WRAPPER_SCRIPT),
            str(input_dir),
            str(temp_output_video),
            str(scale)
        ]

        self._logger.info(f"Running Real-ESRGAN PyTorch wrapper: scale={scale}")
        self._logger.debug(f"Command: {' '.join(cmd)}")

        try:
            # Set environment variables
            env = os.environ.copy()
            env['PREFER'] = 'pytorch'

            # Run wrapper
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=True
            )

            # Log output
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    self._logger.debug(f"[Real-ESRGAN] {line}")

            # Get output frames
            output_frames = sorted(output_dir.glob("*.png"))

            if not output_frames:
                raise VideoProcessingError("No output frames found after Real-ESRGAN processing")

            return output_frames

        except subprocess.TimeoutExpired:
            raise VideoProcessingError(f"Real-ESRGAN processing timed out after {timeout}s")

        except subprocess.CalledProcessError as e:
            error_msg = f"Real-ESRGAN wrapper failed: {e.stderr}"
            self._logger.error(error_msg)
            raise VideoProcessingError(error_msg)

