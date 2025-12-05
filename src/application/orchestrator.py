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
            # Determine target FPS based on mode
            if job.mode == "upscale":
                # Upscale doesn't change frame count or FPS - always use original
                target_fps = video_info.fps
            elif job.mode in ("interp", "both"):
                # Interpolation increases frame count
                target_fps = job.target_fps or (video_info.fps * job.interp_factor)
            else:
                target_fps = job.target_fps or video_info.fps

            output_video = workspace / "output.mp4"

            frame_paths = [f.path for f in processed_frames] if hasattr(processed_frames[0], 'path') else processed_frames

            self._assembler.assemble(frames=frame_paths, output_path=output_video, fps=target_fps)
            self._metrics.stop_timer('assembly')

            # 6. Upload
            self._metrics.start_timer('upload')
            upload_key = self._generate_upload_key(job)
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
                interp_dir = workspace / "interpolated"
                interp_options = {'factor': int(job.interp_factor), 'job_id': job.job_id}
                if isinstance(job.config, dict):
                    interp_options['b2_output_key'] = job.config.get('b2_output_key')
                    interp_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._interpolator.process(frame_paths, interp_dir, **interp_options)
                if not result.success:
                    raise VideoProcessingError(f"Interpolation failed")

                interpolated_frames = sorted(interp_dir.glob("*.png"))
                upscale_dir = workspace / "upscaled"
                upscale_options = {'scale': job.scale, 'job_id': job.job_id}
                if isinstance(job.config, dict):
                    upscale_options['b2_output_key'] = job.config.get('b2_output_key')
                    upscale_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._upscaler.process(interpolated_frames, upscale_dir, **upscale_options)
                if not result.success:
                    raise VideoProcessingError(f"Upscaling failed")
                return sorted(upscale_dir.glob("*.png"))
            else:
                upscale_dir = workspace / "upscaled"
                upscale_options = {'scale': job.scale, 'job_id': job.job_id}
                if isinstance(job.config, dict):
                    upscale_options['b2_output_key'] = job.config.get('b2_output_key')
                    upscale_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._upscaler.process(frame_paths, upscale_dir, **upscale_options)
                if not result.success:
                    raise VideoProcessingError(f"Upscaling failed")

                upscaled_frames = sorted(upscale_dir.glob("*.png"))
                interp_dir = workspace / "interpolated"
                interp_options = {'factor': int(job.interp_factor), 'job_id': job.job_id}
                if isinstance(job.config, dict):
                    interp_options['b2_output_key'] = job.config.get('b2_output_key')
                    interp_options['b2_bucket'] = job.config.get('b2_bucket')
                result = self._interpolator.process(upscaled_frames, interp_dir, **interp_options)
                if not result.success:
                    raise VideoProcessingError(f"Interpolation failed")
                return sorted(interp_dir.glob("*.png"))

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
