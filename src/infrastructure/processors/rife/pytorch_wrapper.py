"""RIFE PyTorch wrapper adapter."""

import subprocess
import os
import time
from collections import deque
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
        """
        Check if RIFE bash wrapper is available.

        For shell-wrapped processors, we only check:
        1. Bash script exists
        2. PyTorch + CUDA available (runtime dependencies)

        We do NOT probe Python RIFE models - the bash script handles that internally.
        """
        try:
            # Check if wrapper script exists
            if not cls.WRAPPER_SCRIPT.exists():
                logger.debug(f"RIFE wrapper script not found: {cls.WRAPPER_SCRIPT}")
                return False

            # Check if PyTorch with CUDA is available
            import torch
            if not torch.cuda.is_available():
                logger.debug("PyTorch CUDA not available for RIFE")
                return False

            # Lightweight syntax check of the wrapper script
            try:
                import subprocess
                rc = subprocess.run(
                    ['bash', '-n', str(cls.WRAPPER_SCRIPT)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                ).returncode
                if rc != 0:
                    logger.warning(f"RIFE wrapper script syntax check failed (rc={rc})")
                    return False
            except Exception as e:
                logger.warning(f"Failed to run syntax check for RIFE wrapper: {e}")
                # Don't fail - proceed assuming script is OK

            logger.debug("RIFE PyTorch wrapper is available")
            return True

        except ImportError:
            logger.debug("PyTorch not available for RIFE")
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
            # Encourage unbuffered Python output from child processes so logs stream in real-time
            env['PYTHONUNBUFFERED'] = '1'
            env['PYTHONIOENCODING'] = 'utf-8'

            # Export job/upload related envs so wrapper scripts can name and upload outputs
            try:
                job_id_opt = options.get('job_id') if isinstance(options, dict) else None
            except Exception:
                job_id_opt = None
            if job_id_opt:
                env['JOB'] = str(job_id_opt)
                env['JOB_ID'] = str(job_id_opt)

            # B2 upload hints: b2_output_key, b2_bucket, b2_endpoint, b2_key, b2_secret
            try:
                b2_out = options.get('b2_output_key') if isinstance(options, dict) else None
            except Exception:
                b2_out = None
            if b2_out:
                env['B2_OUTPUT_KEY'] = str(b2_out)
            try:
                b2_bkt = options.get('b2_bucket') if isinstance(options, dict) else None
            except Exception:
                b2_bkt = None
            if b2_bkt:
                env['B2_BUCKET'] = str(b2_bkt)
            try:
                b2_ep = options.get('b2_endpoint') if isinstance(options, dict) else None
            except Exception:
                b2_ep = None
            if b2_ep:
                env['B2_ENDPOINT'] = str(b2_ep)
            try:
                b2_key = options.get('b2_key') if isinstance(options, dict) else None
            except Exception:
                b2_key = None
            if b2_key:
                env['B2_KEY'] = str(b2_key)
            try:
                b2_secret = options.get('b2_secret') if isinstance(options, dict) else None
            except Exception:
                b2_secret = None
            if b2_secret:
                env['B2_SECRET'] = str(b2_secret)

            # Debug: Log environment
            self.debugger.log_step('set_environment', PREFER='pytorch')

            # Run wrapper and stream output live so user sees progress in real time
            self.debugger.log_step('execute_shell_script', timeout=timeout)
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
            except OSError as e:
                self._logger.error(f"Failed to start wrapper process: {e}")
                raise VideoProcessingError(f"Failed to start RIFE wrapper: {e}")

            self._logger.info(f"Started wrapper pid={proc.pid}")
            # Immediate diagnostics: log script file details and input_arg details so user sees something
            try:
                script_path = Path(self.WRAPPER_SCRIPT)
                script_exists = script_path.exists()
                script_mode = oct(script_path.stat().st_mode & 0o777) if script_exists else 'n/a'
            except Exception:
                script_exists = False
                script_mode = 'n/a'
            self._logger.info(f"Wrapper script exists={script_exists} mode={script_mode} wrapper_path={self.WRAPPER_SCRIPT}")
            try:
                in_path = Path(input_arg)
                if in_path.exists():
                    if in_path.is_dir():
                        files = list(in_path.glob('*'))[:6]
                        files_str = ','.join([p.name for p in files])
                        self._logger.info(f"Input is directory {in_path} contains sample: {files_str}")
                    else:
                        try:
                            sz = in_path.stat().st_size
                            self._logger.info(f"Input file {in_path} exists size={sz}")
                        except Exception:
                            self._logger.info(f"Input file {in_path} exists (size unknown)")
                else:
                    self._logger.info(f"Input argument does not exist on disk: {input_arg}")
            except Exception as e:
                self._logger.info(f"Error while inspecting input_arg: {e}")

            # Keep a rolling buffer of output for diagnostics (avoid unbounded memory)
            MAX_BUFFER_LINES = 2000
            buf = deque(maxlen=MAX_BUFFER_LINES)
            start_ts = time.time()

            # Read lines as they appear using readline so we can insert heartbeat checks
            try:
                if proc.stdout is None:
                    raise VideoProcessingError("Wrapper process had no stdout pipe")

                last_output_ts = time.time()
                # seconds without output before emitting a heartbeat (env override RIFE_HEARTBEAT_INTERVAL)
                try:
                    HEARTBEAT_INTERVAL = int(os.environ.get('RIFE_HEARTBEAT_INTERVAL', '3'))
                except Exception:
                    HEARTBEAT_INTERVAL = 3

                while True:
                    # Try to read a line; readline blocks but we can check process poll periodically
                    line = proc.stdout.readline()
                    if line:
                        line = line.rstrip('\n')
                        buf.append(line)
                        last_output_ts = time.time()
                        # Mirror to logger (info for visibility)
                        self._logger.info(f"[RIFE] {line}")
                    else:
                        # No data available right now
                        if proc.poll() is not None:
                            # Process has exited and no more data
                            break
                        # If we've been waiting longer than heartbeat, log a small heartbeat so user knows we're alive
                        now = time.time()
                        if now - last_output_ts > HEARTBEAT_INTERVAL:
                            self._logger.info(f"[RIFE] (no stdout for {int(now-last_output_ts)}s) still running pid={proc.pid}...")
                            # refresh last_output to avoid spamming
                            last_output_ts = now
                        # Sleep briefly to avoid busy loop
                        time.sleep(0.5)

                # Ensure process has exited (reap)
                proc.wait()
            except subprocess.TimeoutExpired as e:
                # Ensure process terminated
                try:
                    proc.kill()
                except Exception:
                    pass
                error = VideoProcessingError(f"RIFE processing timed out after {timeout}s")
                self.debugger.log_error(error, context="shell_execution")
                self.debugger.log_shell_output(returncode=-1, stdout='\n'.join(list(buf)), stderr='')
                self.debugger.log_end(False, reason="timeout")
                raise error

            # Collect final output
            try:
                remaining_stdout, _ = proc.communicate(timeout=1)
            except Exception:
                remaining_stdout = ''
            if remaining_stdout:
                for line in remaining_stdout.splitlines():
                    buf.append(line)
                    self._logger.info(f"[RIFE] {line}")

            result_stdout = '\n'.join(list(buf))
            result_returncode = proc.returncode if proc.returncode is not None else -1

            # Debug: Log shell output snapshot
            self.debugger.log_shell_output(returncode=result_returncode, stdout=result_stdout, stderr='')

            # If wrapper failed, raise with captured output
            if result_returncode != 0:
                # Truncate for error message
                snippet = (result_stdout[:4000] + '... [truncated]') if len(result_stdout) > 4000 else result_stdout
                error_msg = f"RIFE wrapper failed (rc={result_returncode}).\nLOG:\n{snippet}\n"
                self._logger.error(error_msg)
                error = VideoProcessingError(error_msg)
                self.debugger.log_error(error, context="shell_execution")
                self.debugger.log_end(False, reason="shell_error", exit_code=result_returncode)
                raise error

            # Extract frames from output video
            # The bash wrapper creates a video file, not frames. We must extract them.
            self.debugger.log_step('collect_output_frames', output_dir=str(output_dir))

            # First check if video exists
            if not temp_output_video.exists():
                error = VideoProcessingError(f"Bash wrapper did not create expected output video: {temp_output_video}")
                self.debugger.log_error(error, context="video_not_found")
                self.debugger.log_end(False, output_frames_found=0)
                raise error

            self._logger.info(f"Bash wrapper created video {temp_output_video}, extracting frames for next stage...")

            # Extract frames from the video
            from infrastructure.media import FFmpegExtractor
            extractor = FFmpegExtractor()
            try:
                video_info = extractor.get_video_info(temp_output_video)
                self._logger.info(f"Video info: {video_info.width}x{video_info.height}, {video_info.fps} fps, {video_info.frame_count} frames")

                frames = extractor.extract_frames(video_info, output_dir)
                output_frames = [f.path for f in frames] if hasattr(frames[0], 'path') else frames
                output_frames = sorted(output_frames)
                self._logger.info(f"✓ Extracted {len(output_frames)} frames from interpolated video for next processing stage")
            except Exception as e:
                error = VideoProcessingError(f"Failed to extract frames from output video: {e}")
                self.debugger.log_error(error, context="extracting_frames_from_video")
                self.debugger.log_end(False, output_frames_found=0)
                raise error

            if not output_frames:
                error = VideoProcessingError("Frame extraction produced no frames")
                self.debugger.log_error(error, context="empty_frame_extraction")
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
