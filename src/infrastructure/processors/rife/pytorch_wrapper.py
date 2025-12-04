"""RIFE PyTorch wrapper adapter."""

import subprocess
import os
from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from infrastructure.processors.debug import ProcessorDebugger
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

logger = get_logger(__name__)


class RifePytorchWrapper(BaseProcessor):
    """
    Adapter for PyTorch RIFE implementation.
    Wraps the existing run_rife_pytorch.sh script.

    Debug mode:
        export DEBUG_PROCESSORS=1
        python pipeline_v2.py --mode interp
        # Check /tmp/rife_debug.log for detailed logs
    """

    WRAPPER_SCRIPT = Path("/workspace/project/run_rife_pytorch.sh")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.debugger = ProcessorDebugger('rife')
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
        # Debug: Log start
        self.debugger.log_start(
            num_input_frames=len(input_frames),
            output_dir=str(output_dir),
            options=options
        )

        # Get options
        factor = options.get('factor', 2)
        timeout = options.get('timeout', 3600)

        # Determine input to pass to the wrapper. The wrapper expects a video file path.
        # Upstream code sometimes passes a frames directory (e.g. /tmp/.../frames).
        # Try to locate the original video (common name: input.mp4) in the workspace parent.
        first_input = input_frames[0]
        # If caller passed a directory path as the first item, handle that case
        if first_input.is_dir():
            frames_dir = first_input
        else:
            frames_dir = first_input.parent
        input_candidate = None
        # Common candidate: parent/input.mp4
        parent_dir = frames_dir.parent
        cand = parent_dir / 'input.mp4'
        if cand.exists():
            input_candidate = cand
        else:
            # look for any video file in parent_dir
            for ext in ('mp4','mkv','mov','webm','avi'):
                found = list(parent_dir.glob(f"*.{ext}"))
                if found:
                    input_candidate = found[0]
                    break

        if input_candidate is not None:
            input_arg = str(input_candidate)
            self._logger.debug(f"Detected original input video for wrapper: {input_arg}")
        else:
            # Fallback: pass frames dir (legacy behavior) — but this usually causes the wrapper to fail
            # Prefer to assemble a temporary video here if needed. For now we'll attempt to pass the
            # parent dir input if present; otherwise we pass frames_dir and let the wrapper log a clear error.
            input_arg = str(frames_dir)

        # Prepare output video path (wrapper creates video, we'll extract frames later)
        input_dir = frames_dir
        temp_output_video = output_dir / "interpolated_temp.mp4"

        # Debug: Log paths
        self.debugger.log_step('setup_paths',
            input_dir=str(input_dir),
            output_dir=str(output_dir),
            wrapper_script=str(self.WRAPPER_SCRIPT),
            script_exists=self.WRAPPER_SCRIPT.exists()
        )

        # Build command
        cmd = [
            str(self.WRAPPER_SCRIPT),
            input_arg,
            str(temp_output_video),
            str(factor)
        ]
        self._logger.debug(f"Wrapper will be invoked with input_arg={input_arg}")

        self._logger.info(f"Running RIFE PyTorch wrapper: factor={factor}")
        self._logger.debug(f"Command: {' '.join(cmd)}")

        # Debug: Log command
        self.debugger.log_shell_command(cmd)

        try:
            # Set environment variables
            env = os.environ.copy()
            env['PREFER'] = 'pytorch'

            # Debug: Log environment
            self.debugger.log_step('set_environment', PREFER='pytorch')

            # Run wrapper
            self.debugger.log_step('execute_shell_script', timeout=timeout)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                check=True
            )

            # Debug: Log shell output
            self.debugger.log_shell_output(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr
            )

            # Log output
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    self._logger.debug(f"[RIFE] {line}")

            # Extract frames from output video if needed
            # For now, assume wrapper already created frames in output_dir
            self.debugger.log_step('collect_output_frames', output_dir=str(output_dir))
            output_frames = sorted(output_dir.glob("*.png"))

            if not output_frames:
                # If no frames, the wrapper might have created a video
                # We would need to extract frames here
                # For simplicity, assume frames are present
                error = VideoProcessingError("No output frames found after RIFE processing")
                self.debugger.log_error(error, context="collecting_output_frames")
                self.debugger.log_end(False, output_frames_found=0)
                raise error

            # Debug: Success
            self.debugger.log_end(True,
                output_frames_produced=len(output_frames),
                first_frame=output_frames[0].name if output_frames else None,
                last_frame=output_frames[-1].name if output_frames else None
            )

            return output_frames

        except subprocess.TimeoutExpired as e:
            error = VideoProcessingError(f"RIFE processing timed out after {timeout}s")
            self.debugger.log_error(error, context="shell_execution")
            self.debugger.log_end(False, reason="timeout")
            raise error

        except subprocess.CalledProcessError as e:
            # Build a detailed error message including return code, stdout and stderr
            rc = getattr(e, 'returncode', 'unknown')
            stdout = getattr(e, 'stdout', '') or ''
            stderr = getattr(e, 'stderr', '') or ''
            # Truncate very large outputs to avoid flooding logs
            def _trunc(s, n=4000):
                return (s[:n] + '... [truncated]') if len(s) > n else s

            error_msg = (
                f"RIFE wrapper failed (rc={rc}).\nSTDOUT:\n{_trunc(stdout)}\nSTDERR:\n{_trunc(stderr)}\n"
            )
            self._logger.error(error_msg)
            error = VideoProcessingError(error_msg)
            self.debugger.log_error(error, context="shell_execution")
            self.debugger.log_shell_output(rc, stdout, stderr)
            self.debugger.log_end(False, reason="shell_error", exit_code=rc)
            raise error

        # (no additional fallback - previous block captures details and raises VideoProcessingError)
