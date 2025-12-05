"""Real-ESRGAN PyTorch wrapper adapter."""

import subprocess
import os
from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from infrastructure.processors.debug import ProcessorDebugger
from domain.exceptions import VideoProcessingError, ProcessorNotAvailableError
from shared.logging import get_logger

logger = get_logger(__name__)


class RealESRGANPytorchWrapper(BaseProcessor):
    """
    Adapter for PyTorch Real-ESRGAN implementation.
    Wraps the existing run_realesrgan_pytorch.sh script.

    Debug mode:
        export DEBUG_PROCESSORS=1
        python pipeline_v2.py --mode upscale
        # Check /tmp/realesrgan_debug.log for detailed logs
    """

    WRAPPER_SCRIPT = Path("/workspace/project/run_realesrgan_pytorch.sh")
    REALESRGAN_REPO = Path("/workspace/project/external/Real-ESRGAN")
    REALESRGAN_GIT_URL = "https://github.com/xinntao/Real-ESRGAN.git"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.debugger = ProcessorDebugger('realesrgan')
        # Ensure Real-ESRGAN repo is cloned before checking availability
        self.__class__._ensure_realesrgan_repo()
        if not self.is_available():
            raise ProcessorNotAvailableError("Real-ESRGAN PyTorch wrapper is not available")

    @staticmethod
    def _ensure_realesrgan_repo() -> None:
        """Ensure Real-ESRGAN repository is cloned."""
        repo = RealESRGANPytorchWrapper.REALESRGAN_REPO
        git_url = RealESRGANPytorchWrapper.REALESRGAN_GIT_URL

        if repo.exists() and (repo / "inference_realesrgan.py").exists():
            logger.debug("Real-ESRGAN repo already exists")
            return

        logger.info(f"Cloning Real-ESRGAN from {git_url}...")
        try:
            repo.parent.mkdir(parents=True, exist_ok=True)

            result = subprocess.run(
                ["git", "clone", "--depth", "1", git_url, str(repo)],
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.error(f"Failed to clone Real-ESRGAN: {result.stderr}")
                return

            # Remove the bundled realesrgan package to avoid conflicts
            bundled_pkg = repo / "realesrgan"
            if bundled_pkg.exists():
                import shutil
                shutil.rmtree(bundled_pkg, ignore_errors=True)
                logger.info("Removed bundled realesrgan package to use installed version")

            logger.info("Real-ESRGAN repo cloned successfully")

        except subprocess.TimeoutExpired:
            logger.error("Timeout while cloning Real-ESRGAN repository")
        except Exception as e:
            logger.error(f"Failed to clone Real-ESRGAN: {e}")

    @classmethod
    def is_available(cls) -> bool:
        """Check if PyTorch and CUDA are available."""
        try:
            # Check if wrapper script exists
            if not cls.WRAPPER_SCRIPT.exists():
                logger.debug(f"Wrapper script not found: {cls.WRAPPER_SCRIPT}")
                return False

            # Check if Real-ESRGAN repo exists
            if not cls.REALESRGAN_REPO.exists():
                logger.debug(f"Real-ESRGAN repo not found: {cls.REALESRGAN_REPO}")
                return False

            # Check if PyTorch with CUDA is available
            import torch
            available = torch.cuda.is_available()
            if not available:
                logger.debug("CUDA not available")
            return available
        except ImportError as e:
            logger.debug(f"Import error checking availability: {e}")
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
        # Debug: Log start
        self.debugger.log_start(
            num_input_frames=len(input_frames),
            output_dir=str(output_dir),
            options=options
        )

        # Get options
        scale = options.get('scale', 2)
        timeout = options.get('timeout', 7200)  # 2 hours for upscaling

        # Input/output paths
        input_dir = input_frames[0].parent
        temp_output_video = output_dir / "upscaled_temp.mp4"

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
            str(input_dir),
            str(temp_output_video),
            str(scale)
        ]

        self._logger.info(f"Running Real-ESRGAN PyTorch wrapper: scale={scale}")
        self._logger.debug(f"Command: {' '.join(cmd)}")

        # Debug: Log command
        self.debugger.log_shell_command(cmd)

        try:
            # Set environment variables
            env = os.environ.copy()
            env['PREFER'] = 'pytorch'
            env['AUTO_UPLOAD_B2'] = '1'
            # Disable auto-upload if we're in an intermediate processing stage (e.g. 'both' mode)
            # The orchestrator will handle final upload after all processing is complete
            is_intermediate = options.get('_intermediate_stage', False)
            if is_intermediate:
                env['AUTO_UPLOAD_B2'] = '0'
                self._logger.info("Disabling AUTO_UPLOAD_B2 for intermediate processing stage")

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
                    self._logger.debug(f"[Real-ESRGAN] {line}")

            # Get output frames
            self.debugger.log_step('collect_output_frames', output_dir=str(output_dir))
            output_frames = sorted(output_dir.glob("*.png"))

            if not output_frames:
                error = VideoProcessingError("No output frames found after Real-ESRGAN processing")
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
            error = VideoProcessingError(f"Real-ESRGAN processing timed out after {timeout}s")
            self.debugger.log_error(error, context="shell_execution")
            self.debugger.log_end(False, reason="timeout")
            raise error

        except subprocess.CalledProcessError as e:
            error_msg = f"Real-ESRGAN wrapper failed: {e.stderr}"
            self._logger.error(error_msg)
            error = VideoProcessingError(error_msg)
            self.debugger.log_error(error, context="shell_execution")
            self.debugger.log_shell_output(e.returncode, e.stdout or "", e.stderr or "")
            self.debugger.log_end(False, reason="shell_error", exit_code=e.returncode)
            raise error

