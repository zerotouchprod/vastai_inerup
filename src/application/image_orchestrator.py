"""Main orchestrator for image processing pipeline."""

from pathlib import Path
from typing import Optional
from datetime import datetime

from domain.models import Job, ProcessingResult, UploadResult
from domain.protocols import (
    IDownloader, IProcessor, IUploader, ILogger, IMetricsCollector
)
from domain.exceptions import VideoProcessingError
from shared.logging import get_logger
import tempfile
import shutil

logger = get_logger(__name__)


class ImageProcessingOrchestrator:
    """Main orchestrator - coordinates all components for image processing."""

    def __init__(
        self,
        downloader: IDownloader,
        upscaler: Optional[IProcessor],
        uploader: IUploader,
        logger: ILogger,
        metrics: IMetricsCollector
    ):
        self._downloader = downloader
        self._upscaler = upscaler
        self._uploader = uploader
        self._logger = logger
        self._metrics = metrics

    def process(self, job: Job) -> ProcessingResult:
        """Execute image processing job."""
        self._logger.info(f"Starting image job {job.job_id}: type={job.type}, mode={job.mode}")
        self._metrics.start_timer('total_job')

        workspace = None

        try:
            # 1. Create workspace
            workspace = Path(tempfile.mkdtemp(prefix=f"img_job_{job.job_id}_"))

            # 2. Download image
            self._metrics.start_timer('download')
            # Determine file extension from URL or use default
            input_file = self._downloader.download(job.input_url, workspace / "input_image")
            self._metrics.stop_timer('download')

            # 3. Process image
            self._metrics.start_timer('processing')
            processed_image = self._process_image(job, input_file, workspace)
            self._metrics.stop_timer('processing')

            # 4. Upload
            self._metrics.start_timer('upload')
            upload_key = self._generate_upload_key(job, input_file)
            self._logger.info(f"Resolved upload key for B2: {upload_key}")
            upload_result = self._uploader.upload(processed_image, upload_key)
            self._metrics.stop_timer('upload')

            # 5. Cleanup workspace
            if workspace and workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

            total_time = self._metrics.stop_timer('total_job')

            result = ProcessingResult(
                success=True,
                output_path=processed_image,
                frames_processed=1,  # Single image
                duration_seconds=total_time,
                metrics=self._metrics.get_summary()
            )

            result.add_metric('upload_url', upload_result.url)

            return result

        except Exception as e:
            self._logger.exception(f"Image job {job.job_id} failed: {e}")

            # Cleanup on error
            if workspace and workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=self._metrics.elapsed_time(),
                errors=[str(e)]
            )

    def _process_image(self, job: Job, input_file: Path, workspace: Path) -> Path:
        """Process single image."""
        if not self._upscaler:
            raise VideoProcessingError("Upscaler not available")

        output_dir = workspace / "upscaled"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Process single image
        options = {'scale': job.scale, 'job_id': job.job_id}
        if isinstance(job.config, dict):
            options['b2_output_key'] = job.config.get('b2_output_key')
            options['b2_bucket'] = job.config.get('b2_bucket')

        # The upscaler expects a list of frames, but we have a single image
        result = self._upscaler.process([input_file], output_dir, **options)
        
        if not result.success:
            raise VideoProcessingError(f"Image upscaling failed: {result.errors}")

        # Find the output image
        output_images = list(output_dir.glob("*"))
        if not output_images:
            raise VideoProcessingError("No output image generated")
        
        # Return the first output image
        return output_images[0]

    def _generate_upload_key(self, job: Job, input_file: Path) -> str:
        """Generate S3 key for upload."""
        from urllib.parse import urlparse
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        parsed = urlparse(job.input_url)
        base_name = Path(parsed.path).stem or "image"
        
        # Get original extension
        original_ext = input_file.suffix.lower()
        # Use .png for upscaled images if original was image, otherwise keep original extension
        output_ext = '.png' if original_ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff'] else original_ext

        # 1) prefer explicit B2 output key provided in job.config
        b2_key_cfg = None
        try:
            b2_key_cfg = job.config.get('b2_output_key') if isinstance(job.config, dict) else None
        except Exception:
            b2_key_cfg = None
        if b2_key_cfg:
            # ensure proper extension
            if not b2_key_cfg.lower().endswith(output_ext):
                b2_key_cfg = f"{b2_key_cfg}{output_ext}"
            return b2_key_cfg

        # 2) support b2_output_prefix (directory/prefix on bucket)
        b2_prefix = None
        try:
            b2_prefix = job.config.get('b2_output_prefix') if isinstance(job.config, dict) else None
        except Exception:
            b2_prefix = None
        if b2_prefix:
            # build filename from job id or base name
            filename = (getattr(job, 'job_id', None) or base_name)
            if not str(filename).lower().endswith(output_ext):
                filename = f"{filename}{output_ext}"
            # join prefix and filename
            return f"{b2_prefix.rstrip('/')}/{filename}"

        # 3) next prefer job.job_id as filename
        job_id_name = getattr(job, 'job_id', None)
        if job_id_name:
            fname = job_id_name if job_id_name.lower().endswith(output_ext) else f"{job_id_name}{output_ext}"
            return fname

        # 4) fallback to timestamped key
        return f"images/{base_name}-{timestamp}{output_ext}"
