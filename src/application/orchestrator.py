"""Main orchestrator for video processing pipeline."""

from pathlib import Path
from typing import Optional
from datetime import datetime

from src.domain.models import Job, ProcessingResult
from src.domain.protocols import (
    IDownloader, IExtractor, IProcessor, IAssembler,
    IUploader, ILogger, IMetricsCollector
)
from src.domain.exceptions import VideoProcessingError
from src.shared.logging import get_logger
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
        metrics: IMetricsCollector,
        subtitle_remover: Optional[IProcessor] = None,
        watermark_remover: Optional[IProcessor] = None
    ):
        self._downloader = downloader
        self._extractor = extractor
        self._upscaler = upscaler
        self._interpolator = interpolator
        self._assembler = assembler
        self._uploader = uploader
        self._logger = logger
        self._metrics = metrics
        self._subtitle_remover = subtitle_remover
        self._watermark_remover = watermark_remover

    def process(self, job: Job) -> ProcessingResult:
        """Execute video processing job."""
        self._logger.info(f"Starting job {job.job_id}: type={job.type}, mode={job.mode}")
        self._metrics.start_timer('total_job')

        workspace = None

        try:
            # 1. Create workspace
            workspace = Path(tempfile.mkdtemp(prefix=f"job_{job.job_id}_"))

            # 2. Download
            self._metrics.start_timer('download')
            input_file = self._downloader.download(job.input_url, workspace / "input.mp4")
            self._metrics.stop_timer('download')

            # 2.1. Extract audio BEFORE frame extraction (NEW - v2.0.1)
            audio_path = None
            from src.infrastructure.video.audio_handler import AudioPreserver
            from src.core.config import get_config

            config = get_config()
            if config.PRESERVE_AUDIO:
                try:
                    self._logger.info("Step 0: Extracting audio track for preservation")
                    audio_preserver = AudioPreserver(
                        audio_codec=config.AUDIO_CODEC,
                        audio_bitrate=config.AUDIO_BITRATE,
                        fallback_to_silent=config.FALLBACK_TO_SILENT
                    )

                    audio_path = workspace / "original_audio.aac"
                    has_audio = audio_preserver.extract_audio(input_file, audio_path)

                    if has_audio:
                        self._logger.info(f"✅ Audio extracted successfully: {audio_path}")
                        # Get audio info for logging
                        audio_info = audio_preserver.get_audio_info(audio_path)
                        if audio_info:
                            self._logger.info(
                                f"Audio: {audio_info['codec']}, "
                                f"{audio_info['duration']:.2f}s, "
                                f"{audio_info.get('bitrate', 'unknown')}kbps"
                            )
                    else:
                        self._logger.warning("⚠️ No audio track found in input video")
                        audio_path = None

                except Exception as e:
                    self._logger.warning(f"⚠️ Audio extraction failed: {e}")
                    if config.FALLBACK_TO_SILENT:
                        self._logger.info("Continuing with silent video (fallback mode)")
                        audio_path = None
                    else:
                        raise

            # 2.5. For subtitle removal mode, test the processor before extracting frames
            if job.mode == "remove-subtitles":
                self._test_subtitle_remover()

            # 3. Extract frames
            self._metrics.start_timer('extraction')
            video_info = self._extractor.get_video_info(input_file)
            frames = self._extractor.extract_frames(video_info, workspace / "frames")
            self._metrics.stop_timer('extraction')

            # Compute target FPS to maintain original video duration
            original_fps = 24.0  # Default fallback
            original_duration = None
            try:
                original_frame_count = len(frames)
                original_fps = float(video_info.fps)
                original_duration = original_frame_count / original_fps if original_fps > 0 else None
            except Exception:
                pass  # Use defaults

            # Calculate interp_factor if target_fps is provided (must happen before _process_frames)
            if getattr(job, 'target_fps', None) and job.mode == 'interp':
                if original_fps > 0:
                    calculated_factor = max(2, round(float(job.target_fps) / original_fps))
                    # Always set interp_factor to calculated value
                    job.interp_factor = calculated_factor
                    self._logger.info(f"Calculated interp_factor: {calculated_factor}x (from target FPS {job.target_fps} / original FPS {original_fps})")
                else:
                    self._logger.warning(f"Original FPS is zero or unknown, using default interp_factor")

            # 4. Process frames
            self._metrics.start_timer('processing')
            processed_frames = self._process_frames(job, frames, workspace)
            self._metrics.stop_timer('processing')
            
            self._logger.info(f"✅ Frame processing completed. Got {len(processed_frames)} processed frames")

            # 5. Assemble
            self._metrics.start_timer('assembly')
            self._logger.info("Starting video assembly...")

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
                expected_duration = processed_frame_count / target_fps if target_fps > 0 else 0

                self._logger.info(f"═══ INTERPOLATION FPS CALCULATION ═══")
                self._logger.info(f"Input frames: {original_frame_count} @ {original_fps:.2f} fps = {original_duration:.2f}s")
                self._logger.info(f"Interpolation factor: {interp_factor}x")
                self._logger.info(f"Output frames: {processed_frame_count}")
                self._logger.info(f"Target FPS: {original_fps:.2f} × {interp_factor} = {target_fps:.2f} fps")
                self._logger.info(f"Expected duration: {processed_frame_count} ÷ {target_fps:.2f} = {expected_duration:.2f}s")

                # Verify frame count matches expectation
                expected_frames = original_frame_count + (original_frame_count - 1) * (interp_factor - 1)
                if processed_frame_count != expected_frames:
                    self._logger.warning(
                        f"⚠️ Frame count discrepancy: expected {expected_frames} frames "
                        f"({original_frame_count} + {original_frame_count-1} pairs × {interp_factor-1} mids), "
                        f"got {processed_frame_count} (difference: {processed_frame_count - expected_frames})"
                    )

                if original_duration and abs(expected_duration - original_duration) > 0.5:
                    self._logger.warning(
                        f"⚠️ Duration mismatch detected! "
                        f"Original: {original_duration:.2f}s, Expected after interp: {expected_duration:.2f}s "
                        f"(difference: {abs(expected_duration - original_duration):.2f}s)"
                    )

                self._logger.info(f"═══════════════════════════════════")

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
            try:
                self._assembler.assemble(frames=frame_paths, output_path=output_video, fps=target_fps)
                self._logger.info(f"✅ Video assembly completed: {output_video}")
            except Exception as e:
                self._logger.error(f"❌ Video assembly failed: {e}")
                raise
            self._metrics.stop_timer('assembly')

            # 5.5. Merge audio back (NEW - v2.0.1)
            final_video = output_video
            if config.PRESERVE_AUDIO and audio_path and audio_path.exists():
                try:
                    self._logger.info("Step 6: Merging audio track back into video")
                    final_video = workspace / "final_with_audio.mp4"

                    audio_preserver.merge_audio_video(
                        video_path=output_video,
                        audio_path=audio_path,
                        output_path=final_video
                    )

                    self._logger.info(f"✅ Audio merged successfully: {final_video}")

                    # Update output_video to point to final video with audio
                    output_video = final_video

                except Exception as e:
                    self._logger.warning(f"⚠️ Audio merge failed: {e}")
                    if config.FALLBACK_TO_SILENT:
                        self._logger.info("Using silent video (audio merge failed)")
                        # output_video remains the silent version
                    else:
                        raise
            elif not config.PRESERVE_AUDIO:
                self._logger.info("Audio preservation disabled in config")
            else:
                self._logger.info("No audio to merge (video was silent)")

            # 6. Upload
            self._metrics.start_timer('upload')
            upload_key = self._generate_upload_key(job)
            # Log the resolved upload key so CLI/remote logs show where the file will be uploaded
            self._logger.info(f"Resolved upload key for B2: {upload_key}")
            self._logger.info(f"Uploading {output_video} ({output_video.stat().st_size / 1024 / 1024:.1f} MB) to B2...")
            try:
                upload_result = self._uploader.upload(output_video, upload_key)
                self._logger.info(f"✅ Upload completed: {upload_result.url}")
            except Exception as e:
                self._logger.error(f"❌ Upload failed: {e}")
                raise
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

            input_frame_count = len(frame_paths)
            self._logger.info(f"Starting interpolation: {input_frame_count} input frames × {job.interp_factor}x factor")

            result = self._interpolator.process(frame_paths, output_dir, **options)
            if not result.success:
                raise VideoProcessingError(f"Interpolation failed: {result.errors}")

            # Verify interpolated frames
            interpolated_frames = sorted(output_dir.glob("*.png"))
            actual_count = len(interpolated_frames)
            # Expected: original_frames + (original_frames-1) * (factor-1) intermediate frames
            expected_count = input_frame_count + (input_frame_count - 1) * (int(job.interp_factor) - 1)

            self._logger.info(f"Interpolation complete: {actual_count} output frames (expected: {expected_count})")

            if actual_count != expected_count:
                self._logger.warning(
                    f"⚠️ Frame count mismatch after interpolation! "
                    f"Expected {expected_count} frames, got {actual_count} "
                    f"(input: {input_frame_count}, factor: {job.interp_factor}x)"
                )

            if actual_count == 0:
                raise VideoProcessingError(f"No interpolated frames found in {output_dir}")

            return interpolated_frames

        elif job.mode == "remove-subtitles":
            if not self._subtitle_remover:
                raise VideoProcessingError("Subtitle remover not available")
            output_dir = workspace / "subtitles_removed"
            options = {'job_id': job.job_id}
            if isinstance(job.config, dict):
                options['b2_output_key'] = job.config.get('b2_output_key')
                options['b2_bucket'] = job.config.get('b2_bucket')
            # Use subtitle remover processor
            self._logger.info(f"Starting subtitle removal for {len(frame_paths)} frames")
            result = self._subtitle_remover.process(frame_paths, output_dir, **options)
            if not result.success:
                raise VideoProcessingError(f"Subtitle removal failed: {result.errors}")
            
            # Debug: list files in output directory
            all_files = list(output_dir.iterdir())
            self._logger.info(f"Subtitle removal completed. Output directory contains {len(all_files)} files")
            if all_files:
                self._logger.info(f"First 5 files: {[f.name for f in all_files[:5]]}")
                # Check file extensions
                extensions = {}
                for f in all_files:
                    ext = f.suffix.lower()
                    extensions[ext] = extensions.get(ext, 0) + 1
                self._logger.info(f"File extensions: {extensions}")
            
            # Look for both .png and .jpg files
            processed_frames = sorted(output_dir.glob("*.png")) + sorted(output_dir.glob("*.jpg"))
            self._logger.info(f"Found {len(processed_frames)} processed frames (.png + .jpg)")
            
            if not processed_frames:
                raise VideoProcessingError(f"No processed frames found in {output_dir}")
            
            return processed_frames

        elif job.mode == "remove-watermark":
            if not self._watermark_remover:
                raise VideoProcessingError("Watermark remover not available")
            output_dir = workspace / "watermark_removed"
            options = {'job_id': job.job_id}
            if isinstance(job.config, dict):
                options['b2_output_key'] = job.config.get('b2_output_key')
                options['b2_bucket'] = job.config.get('b2_bucket')
            # Use watermark remover processor
            self._logger.info(f"Starting watermark removal for {len(frame_paths)} frames")
            result = self._watermark_remover.process(frame_paths, output_dir, **options)
            if not result.success:
                raise VideoProcessingError(f"Watermark removal failed: {result.errors}")

            # Debug: list files in output directory
            all_files = list(output_dir.iterdir())
            self._logger.info(f"Watermark removal completed. Output directory contains {len(all_files)} files")
            if all_files:
                self._logger.info(f"First 5 files: {[f.name for f in all_files[:5]]}")
                # Check file extensions
                extensions = {}
                for f in all_files:
                    ext = f.suffix.lower()
                    extensions[ext] = extensions.get(ext, 0) + 1
                self._logger.info(f"File extensions: {extensions}")

            # Look for both .png and .jpg files
            processed_frames = sorted(output_dir.glob("*.png")) + sorted(output_dir.glob("*.jpg"))
            self._logger.info(f"Found {len(processed_frames)} processed frames (.png + .jpg)")

            if not processed_frames:
                raise VideoProcessingError(f"No processed frames found in {output_dir}")

            return processed_frames

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
        elif job.mode == "remove-subtitles":
            return f"subtitles_removed/{base_name}-{timestamp}.mp4"
        elif job.mode == "remove-watermark":
            return f"watermark_removed/{base_name}-{timestamp}.mp4"
        else:
            return f"both/{base_name}-{timestamp}.mp4"

    def _test_subtitle_remover(self):
        """Test if subtitle remover is functional before extracting frames."""
        if not self._subtitle_remover:
            raise VideoProcessingError("Subtitle remover not available")
        
        self._logger.info("Testing subtitle remover functionality...")
        
        # Try to create a simple test to verify the processor works
        # We'll check if the processor has the required methods
        if not hasattr(self._subtitle_remover, 'process'):
            raise VideoProcessingError("Subtitle remover doesn't have required 'process' method")
        
        # For native subtitle remover, we can check if PaddleOCR is available
        # by checking the wrapper's is_available method if it exists
        if hasattr(self._subtitle_remover, 'is_available'):
            # This is a class method on the wrapper
            from src.infrastructure.processors.subtitle.wrapper import SubtitleRemoverWrapper
            if not SubtitleRemoverWrapper.is_available():
                raise VideoProcessingError("Subtitle remover dependencies not available (PaddleOCR, OpenCV)")
        
        self._logger.info("Subtitle remover test passed")
