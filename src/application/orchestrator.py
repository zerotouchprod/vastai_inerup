"""Main orchestrator for video processing pipeline."""

from pathlib import Path
from typing import Optional
from datetime import datetime

from domain.models import ProcessingJob, ProcessingResult
from domain.protocols import (
    IDownloader, IExtractor, IProcessor, IAssembler,
    IUploader, ILogger, IMetricsCollector
)
from domain.exceptions import VideoProcessingError
from shared.logging import get_logger
import tempfile
import shutil

logger = get_logger(__name__)


class VideoProcessingOrchestrator:
    """Main orchestrator - coordinates all components."""

    def __init__(
        self,
        downloader: IDownloader,
        extractor: IExtractor,
        upscaler: Optional[IProcessor],
        interpolator: Optional[IProcessor],
        assembler: IAssembler,
        uploader: IUploader,
        logger: ILogger,
        metrics: IMetricsCollector
    ):
        self._downloader = downloader
        self._extractor = extractor
        self._upscaler = upscaler
        self._interpolator = interpolator
        self._assembler = assembler
        self._uploader = uploader
        self._logger = logger
        self._metrics = metrics

    def process(self, job: ProcessingJob) -> ProcessingResult:
        """Execute video processing job."""
        self._logger.info(f"Starting job {job.job_id}: mode={job.mode}")
        self._metrics.start_timer('total_job')

        workspace = None

        try:
            # 1. Create workspace
            workspace = Path(tempfile.mkdtemp(prefix=f"job_{job.job_id}_"))

            # 2. Download
            self._metrics.start_timer('download')
            input_file = self._downloader.download(job.input_url, workspace / "input.mp4")
            self._metrics.stop_timer('download')

            # 3. Extract frames
            self._metrics.start_timer('extraction')
            video_info = self._extractor.get_video_info(input_file)
            frames = self._extractor.extract_frames(video_info, workspace / "frames")
            self._metrics.stop_timer('extraction')

            # 4. Process frames
            self._metrics.start_timer('processing')
            processed_frames = self._process_frames(job, frames, workspace)
            self._metrics.stop_timer('processing')

            # 5. Assemble
            self._metrics.start_timer('assembly')

            # Normalize processed frame paths to strings (Path or str accepted downstream)
            if not processed_frames:
                raise VideoProcessingError("No processed frames to assemble")

            # If processed_frames elements are objects with .path attribute (legacy), extract those.
            if hasattr(processed_frames[0], 'path'):
                frame_paths = [str(f.path) for f in processed_frames]
            else:
                # Convert Path objects to strings, leave strings intact
                frame_paths = [str(p) for p in processed_frames]

            output_video = workspace / "output.mp4"

            # Compute target FPS to maintain original video duration
            original_fps = 24.0  # Default fallback
            original_duration = None
            try:
                original_frame_count = len(frames)
                original_fps = float(video_info.fps)
                original_duration = original_frame_count / original_fps if original_fps > 0 else None
            except Exception:
                pass  # Use defaults

            processed_frame_count = len(frame_paths)

            # Calculate target FPS based on mode and available information
            if getattr(job, 'target_fps', None):
                # Explicit target FPS takes priority
                target_fps = float(job.target_fps)
                self._logger.info(f"Using explicit target FPS: {target_fps}")
            elif job.mode == 'interp':
                # For interpolation: MULTIPLY the FPS by the interpolation factor
                # More frames at higher FPS = same duration, smoother motion
                # Example: 145→289 frames @ 48 fps (24*2) → stays 6s but smoother
                interp_factor = int(job.interp_factor) if hasattr(job, 'interp_factor') else 2
                target_fps = original_fps * interp_factor
                expected_duration = processed_frame_count / target_fps
                self._logger.info(f"Interp mode: {processed_frame_count} frames @ {target_fps} fps (was {original_fps} fps * {interp_factor}x factor) = {expected_duration:.2f}s (original duration)")
            elif job.mode == 'both' and original_duration and original_duration > 0:
                # For 'both' mode, calculate FPS to maintain original duration
                target_fps = max(1.0, float(processed_frame_count) / original_duration)
                self._logger.info(f"Both mode: {processed_frame_count} frames / {original_duration:.2f}s = {target_fps:.2f} fps")
            elif original_duration and original_duration > 0:
                # Derive FPS from processed frames and original duration
                target_fps = max(1.0, float(processed_frame_count) / original_duration)
                self._logger.info(f"Derived FPS: {processed_frame_count} frames / {original_duration:.2f}s = {target_fps:.2f} fps")
            else:
                # Fallback to original video FPS
                target_fps = float(getattr(video_info, 'fps', 24.0))
                self._logger.info(f"Using fallback FPS: {target_fps}")

            self._logger.info(f"Assembly: {processed_frame_count} frames at {target_fps:.2f} fps = {processed_frame_count/target_fps:.2f}s duration")
            self._assembler.assemble(frames=frame_paths, output_path=output_video, fps=target_fps)
            self._metrics.stop_timer('assembly')

            # 6. Upload
            self._metrics.start_timer('upload')
            upload_key = self._generate_upload_key(job)
            # Log the resolved upload key so CLI/remote logs show where the file will be uploaded
            self._logger.info(f"Resolved upload key for B2: {upload_key}")
            upload_result = self._uploader.upload(output_video, upload_key)
            self._metrics.stop_timer('upload')

            # 7. Cleanup workspace
            if workspace and workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

            total_time = self._metrics.stop_timer('total_job')

            result = ProcessingResult(
                success=True,
                output_path=output_video,
                frames_processed=len(processed_frames),
                duration_seconds=total_time,
                metrics=self._metrics.get_summary()
            )

            result.add_metric('upload_url', upload_result.url)

            return result

        except Exception as e:
            self._logger.exception(f"Job {job.job_id} failed: {e}")

            # Cleanup on error (keep workspace for debugging)
            # if workspace and workspace.exists():
            #     shutil.rmtree(workspace, ignore_errors=True)

            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=self._metrics.elapsed_time(),
                errors=[str(e)]
            )

    def _process_frames(self, job, frames, workspace):
        """Process frames based on mode."""
        frame_paths = [f.path for f in frames] if hasattr(frames[0], 'path') else frames

        if job.mode == "upscale":
            if not self._upscaler:
                raise VideoProcessingError("Upscaler not available")
            output_dir = workspace / "upscaled"
            options = {'scale': job.scale, 'job_id': job.job_id}
            # include b2 overrides if present
            if isinstance(job.config, dict):
                options['b2_output_key'] = job.config.get('b2_output_key')
                options['b2_bucket'] = job.config.get('b2_bucket')
            result = self._upscaler.process(frame_paths, output_dir, **options)
            if not result.success:
                raise VideoProcessingError(f"Upscaling failed: {result.errors}")
            return sorted(output_dir.glob("*.png"))

        elif job.mode == "interp":
            if not self._interpolator:
                raise VideoProcessingError("Interpolator not available")
            output_dir = workspace / "interpolated"
            options = {'factor': int(job.interp_factor), 'job_id': job.job_id}
            if isinstance(job.config, dict):
                options['b2_output_key'] = job.config.get('b2_output_key')
                options['b2_bucket'] = job.config.get('b2_bucket')
            result = self._interpolator.process(frame_paths, output_dir, **options)
            if not result.success:
                raise VideoProcessingError(f"Interpolation failed: {result.errors}")
            return sorted(output_dir.glob("*.png"))

        elif job.mode == "both":
            if not self._upscaler or not self._interpolator:
                raise VideoProcessingError("Both processors required")

            if job.strategy == "interp-then-upscale":
                # Step 1: Interpolation (intermediate stage - no upload)
                interp_dir = workspace / "interpolated"
                interp_options = {
                    'factor': int(job.interp_factor),
                    'job_id': job.job_id,
                    '_intermediate_stage': True  # Don't upload intermediate results
                }
                if isinstance(job.config, dict):
                    interp_options['b2_output_key'] = job.config.get('b2_output_key')
                    interp_options['b2_bucket'] = job.config.get('b2_bucket')
                interp_result = self._interpolator.process(frame_paths, interp_dir, **interp_options)
                if not interp_result.success:
                    raise VideoProcessingError(f"Interpolation failed")

                # Step 2: Upscaling (final stage - orchestrator will upload assembled video)
                # List all files in interpolated directory (including symlinks)
                all_files = []
                for item in sorted(interp_dir.iterdir()):
                    if item.is_file() or item.is_symlink():
                        if item.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                            all_files.append(item)

                self._logger.info(f"Found {len(all_files)} interpolated frames for upscaling")
                expected_frames = len(frame_paths) * int(job.interp_factor) - (len(frame_paths) - 1)
                self._logger.info(f"Expected ~{expected_frames} frames after {job.interp_factor}x interpolation")

                if len(all_files) == 0:
                    # Debug: list ALL files in directory
                    all_items = list(interp_dir.iterdir())
                    self._logger.error(f"No image files found! Directory contains {len(all_items)} items:")
                    for item in all_items[:20]:  # Show first 20
                        self._logger.error(f"  - {item.name} (is_file={item.is_file()}, is_symlink={item.is_symlink()}, suffix={item.suffix})")
                    raise VideoProcessingError(f"No interpolated frames found in {interp_dir}")

                if len(all_files) > 0:
                    self._logger.debug(f"First 5 frames: {[f.name for f in all_files[:5]]}")
                    self._logger.debug(f"Last 5 frames: {[f.name for f in all_files[-5:]]}")

                interpolated_frames = all_files

                upscale_dir = workspace / "upscaled"
                upscale_options = {
                    'scale': job.scale,
                    'job_id': job.job_id,
                    '_intermediate_stage': True  # Don't upload intermediate results
                }
                if isinstance(job.config, dict):
                    upscale_options['b2_output_key'] = job.config.get('b2_output_key')
                    upscale_options['b2_bucket'] = job.config.get('b2_bucket')
                upscale_result = self._upscaler.process(interpolated_frames, upscale_dir, **upscale_options)
                if not upscale_result.success:
                    raise VideoProcessingError(f"Upscaling failed")

                # Return upscaled frames
                upscaled_frames = sorted(upscale_dir.glob("*.png"))
                self._logger.info(f"Upscaling produced {len(upscaled_frames)} frames from {len(interpolated_frames)} interpolated frames")
                if len(upscaled_frames) == 0:
                    raise VideoProcessingError(f"No upscaled frames found in {upscale_dir}")
                return upscaled_frames
            else:
                # Step 1: Upscaling (intermediate stage - no upload)
                upscale_dir = workspace / "upscaled"
                upscale_options = {
                    'scale': job.scale,
                    'job_id': job.job_id,
                    '_intermediate_stage': True  # Don't upload intermediate results
                }
                if isinstance(job.config, dict):
                    upscale_options['b2_output_key'] = job.config.get('b2_output_key')
                    upscale_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._upscaler.process(frame_paths, upscale_dir, **upscale_options)
                if not result.success:
                    raise VideoProcessingError(f"Upscaling failed")

                # Step 2: Interpolation (final stage - orchestrator will upload assembled video)
                upscaled_frames = sorted(upscale_dir.glob("*.png"))
                self._logger.info(f"Found {len(upscaled_frames)} upscaled frames for interpolation")
                if len(upscaled_frames) == 0:
                    raise VideoProcessingError(f"No upscaled frames found in {upscale_dir}")

                interp_dir = workspace / "interpolated"
                interp_options = {
                    'factor': int(job.interp_factor),
                    'job_id': job.job_id,
                    '_intermediate_stage': True  # Don't upload intermediate results
                }
                if isinstance(job.config, dict):
                    interp_options['b2_output_key'] = job.config.get('b2_output_key')
                    interp_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._interpolator.process(upscaled_frames, interp_dir, **interp_options)
                if not result.success:
                    raise VideoProcessingError(f"Interpolation failed")

                final_frames = sorted(interp_dir.glob("*.png"))
                self._logger.info(f"Interpolation produced {len(final_frames)} frames from {len(upscaled_frames)} upscaled frames")
                expected_frames = len(upscaled_frames) * int(job.interp_factor) - (len(upscaled_frames) - 1)
                if len(final_frames) != expected_frames:
                    self._logger.warning(f"Frame count unexpected! Got: {len(final_frames)}, Expected: {expected_frames}")

                return final_frames

    def _generate_upload_key(self, job):
        """Generate S3 key for upload."""
        from urllib.parse import urlparse
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        parsed = urlparse(job.input_url)
        base_name = Path(parsed.path).stem or "video"

        # 1) prefer explicit B2 output key provided in job.config or environment
        b2_key_cfg = None
        try:
            b2_key_cfg = job.config.get('b2_output_key') if isinstance(job.config, dict) else None
        except Exception:
            b2_key_cfg = None
        if b2_key_cfg:
            # ensure .mp4 extension
            if not b2_key_cfg.lower().endswith('.mp4'):
                b2_key_cfg = f"{b2_key_cfg}.mp4"
            return b2_key_cfg

        # 1.5) support b2_output_prefix (directory/prefix on bucket)
        b2_prefix = None
        try:
            b2_prefix = job.config.get('b2_output_prefix') if isinstance(job.config, dict) else None
        except Exception:
            b2_prefix = None
        if b2_prefix:
            # build filename from job id or base name
            filename = (getattr(job, 'job_id', None) or base_name)
            if not str(filename).lower().endswith('.mp4'):
                filename = f"{filename}.mp4"
            # join prefix and filename
            return f"{b2_prefix.rstrip('/')}/{filename}"

        # 2) next prefer job.job_id as filename (plain name or with .mp4)
        job_id_name = getattr(job, 'job_id', None)
        if job_id_name:
            fname = job_id_name if job_id_name.lower().endswith('.mp4') else f"{job_id_name}.mp4"
            return fname

        # 3) fallback to timestamped key using original input basename
        if job.mode == "upscale":
            return f"upscales/{base_name}-{timestamp}.mp4"
        elif job.mode == "interp":
            return f"interp/{base_name}-{timestamp}.mp4"
        else:
            return f"both/{base_name}-{timestamp}.mp4"
