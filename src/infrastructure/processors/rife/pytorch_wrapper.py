"""RIFE PyTorch wrapper adapter."""

import subprocess
import os
from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

logger = get_logger(__name__)


class RifePytorchWrapper(BaseProcessor):
    """
    Adapter for PyTorch RIFE implementation.
    Wraps the existing run_rife_pytorch.sh script.
    """

    WRAPPER_SCRIPT = Path("/workspace/project/run_rife_pytorch.sh")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.is_available():
            raise ProcessorNotAvailableError("RIFE PyTorch wrapper is not available")

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
        """RIFE PyTorch uses GPU."""
        return True

    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
    ) -> List[Path]:
        """
        Execute RIFE interpolation via wrapper script.

        Args:
            input_frames: Input frame paths
            output_dir: Output directory
            options: Processing options (factor, etc.)

        Returns:
            List of interpolated frame paths

        Raises:
            VideoProcessingError: If processing fails
        """
        # Get options
        factor = options.get('factor', 2)
        timeout = options.get('timeout', 3600)

        # Create temporary video from frames (RIFE wrapper expects video input)
        # For now, we'll assume frames are in a directory and let the wrapper handle it
        input_dir = input_frames[0].parent

        # Prepare output video path (wrapper creates video, we'll extract frames later)
        temp_output_video = output_dir / "interpolated_temp.mp4"

        # Build command
        cmd = [
            str(self.WRAPPER_SCRIPT),
            str(input_dir),  # Input (will be handled by wrapper)
            str(temp_output_video),
            str(factor)
        ]

        self._logger.info(f"Running RIFE PyTorch wrapper: factor={factor}")
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
                    self._logger.debug(f"[RIFE] {line}")

            # Extract frames from output video if needed
            # For now, assume wrapper already created frames in output_dir
            output_frames = sorted(output_dir.glob("*.png"))

            if not output_frames:
                # If no frames, the wrapper might have created a video
                # We would need to extract frames here
                # For simplicity, assume frames are present
                raise VideoProcessingError("No output frames found after RIFE processing")

            return output_frames

        except subprocess.TimeoutExpired:
            raise VideoProcessingError(f"RIFE processing timed out after {timeout}s")

        except subprocess.CalledProcessError as e:
            error_msg = f"RIFE wrapper failed: {e.stderr}"
            self._logger.error(error_msg)
            raise VideoProcessingError(error_msg)

