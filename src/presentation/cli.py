"""CLI interface for video processing pipeline."""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

from src.domain.models import Job
from src.domain.exceptions import DomainException, ProcessorNotAvailableError
from src.infrastructure.config import ConfigLoader
from src.infrastructure.io import HttpDownloader, B2S3Uploader
from src.infrastructure.media import FFmpegExtractor, FFmpegAssembler
from src.application.factories import ProcessorFactory
from src.shared.logging import setup_logger, LoggerAdapter, get_logger
from src.shared.metrics import MetricsCollector
from botocore.exceptions import ClientError
from src.application.orchestrator import VideoProcessingOrchestrator
from src.application.image_orchestrator import ImageProcessingOrchestrator


def create_orchestrator_from_config(config, allow_fallback: bool = False):
    """Create orchestrator with all dependencies from src.config."""
    downloader = HttpDownloader()
    
    # Create uploader if configured
    uploader = None
    if config.b2_bucket and config.b2_key and config.b2_secret:
        uploader = B2S3Uploader(
            bucket=config.b2_bucket,
            endpoint=config.b2_endpoint or "https://s3.us-west-004.backblazeb2.com",
            access_key=config.b2_key,
            secret_key=config.b2_secret,
            region=getattr(config, 'b2_region', None)
        )

        # Preliminary pre-check: ensure bucket is accessible with provided creds
        try:
            # Use head_bucket to validate access; will raise ClientError on failure
            uploader._client.head_bucket(Bucket=uploader.bucket)
            get_logger(__name__).info(f"B2 pre-check: bucket '{uploader.bucket}' accessible")
        except ClientError as e:
            raise DomainException(f"B2 pre-check failed: cannot access bucket '{uploader.bucket}' with provided credentials/endpoint: {e}")
        except Exception as e:
            raise DomainException(f"B2 pre-check failed: unexpected error when accessing bucket '{uploader.bucket}': {e}")
    else:
        # Dummy uploader
        from src.domain.models import UploadResult
        class DummyUploader:
            def upload(self, file_path, key):
                return UploadResult(success=True, url=f"file://{file_path}", bucket="local", key=key, size_bytes=0)
        uploader = DummyUploader()

    # Create processors
    factory = ProcessorFactory()
    upscaler = None
    interpolator = None
    subtitle_remover = None

    # Create subtitle remover only for remove-subtitles mode
    subtitle_remover = None
    if config.mode == 'remove-subtitles':
        try:
            subtitle_remover = factory.create_subtitle_remover(
                prefer=config.prefer,
                lang=config.subtitle_language
            )
            get_logger(__name__).info(f"Subtitle remover created (language: {config.subtitle_language})")
        except Exception as e:
            if config.strict:
                raise
            get_logger(__name__).warning(f"Subtitle remover not available: {e}")
            # If subtitle remover fails but we're not strict, continue without it
            subtitle_remover = None

    try:
        if config.mode in ('upscale', 'both', 'image'):
            upscaler = factory.create_upscaler(prefer=config.prefer)
        elif config.mode == 'remove-subtitles':
            # If mode is explicitly remove-subtitles, we still need a subtitle remover
            if not subtitle_remover:
                subtitle_remover = factory.create_subtitle_remover(
                    prefer=config.prefer,
                    lang=config.subtitle_language
                )
    except Exception as e:
        if config.strict:
            raise
        get_logger(__name__).warning(f"Upscaler not available: {e}")

    # Determine orchestrator based on type
    if config.type == 'image':
        logger = LoggerAdapter(get_logger('image_orchestrator'))
        metrics = MetricsCollector()
        
        return ImageProcessingOrchestrator(
            downloader=downloader,
            upscaler=upscaler,
            uploader=uploader,
            logger=logger,
            metrics=metrics
        )
    
    # For video and audio types, create video components (audio processing uses video pipeline for now)
    extractor = FFmpegExtractor()
    assembler = FFmpegAssembler()

    # For subtitle removal mode, use subtitle remover as upscaler
    if config.mode == 'remove-subtitles':
        upscaler = subtitle_remover

    # Only create interpolator for video type with interp/both modes
    if config.type == 'video' and config.mode in ('interp', 'both'):
        try:
            # Mandatory RIFE availability probe: check both native and pytorch wrappers.
            native_ok = False
            try:
                from src.infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
                native_ok = RIFENativeWrapper.is_available()
            except Exception:
                native_ok = False

            pytorch_ok = False
            try:
                from src.infrastructure.processors.rife.pytorch_wrapper import RifePytorchWrapper
                pytorch_ok = RifePytorchWrapper.is_available()
            except Exception:
                pytorch_ok = False

            if not (native_ok or pytorch_ok):
                # No RIFE backend passed probe. By default (allow_fallback=False) fail early.
                msg = "No usable RIFE backend available (probe failed)"
                if config.strict or not allow_fallback:
                    raise ProcessorNotAvailableError(msg)
                get_logger(__name__).warning(msg + " — continuing because allow_fallback=True")

            interpolator = factory.create_interpolator(prefer=config.prefer)
        except Exception as e:
            # If interpolation mode requested but no RIFE backend is available,
            # by default we should fail early (no silent fallback to ffmpeg).
            # allow_fallback toggles whether to continue when RIFE isn't available.
            if config.strict or not allow_fallback:
                # Propagate exception to CLI which will terminate the run.
                raise
            get_logger(__name__).warning(f"Interpolator not available: {e}")

    logger = LoggerAdapter(get_logger('orchestrator'))
    metrics = MetricsCollector()

    return VideoProcessingOrchestrator(
        downloader=downloader,
        extractor=extractor,
        upscaler=upscaler,
        interpolator=interpolator,
        assembler=assembler,
        uploader=uploader,
        logger=logger,
        metrics=metrics,
        subtitle_remover=subtitle_remover
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Video processing pipeline")
    parser.add_argument('--config', type=Path, help='Config YAML file')
    parser.add_argument('--input', '-i', help='Input video URL')
    parser.add_argument('--output', '-o', type=Path, help='Output directory (default: ./output)')
    parser.add_argument('--bucket', '-b', help='B2 bucket name (overrides B2_BUCKET in config/env)')
    parser.add_argument('--b2-endpoint', help='B2 S3-compatible endpoint URL (overrides B2_ENDPOINT)')
    parser.add_argument('--b2-key', help='B2 access key (overrides B2_KEY)')
    parser.add_argument('--b2-secret', help='B2 secret key (overrides B2_SECRET)')
    parser.add_argument('--b2-region', help='B2 region name (overrides B2_REGION)')
    parser.add_argument('--type', choices=['video', 'image', 'audio'], default='video', help='Media type (default: video)')
    parser.add_argument('--mode', help='Processing mode: for video: upscale, interp, both, remove-subtitles; for image: upscale, hdr, denoise; for audio: remove_reverb, enhance, normalize')
    parser.add_argument('--scale', type=float, help='Upscale factor')
    parser.add_argument('--target-fps', type=int, help='Target FPS')
    parser.add_argument('--prefer', choices=['auto', 'pytorch'], help='Backend')
    parser.add_argument('--strategy', choices=['interp-then-upscale', 'upscale-then-interp'], help='Processing order for "both" mode (default: interp-then-upscale)')
    parser.add_argument('--image-mode', choices=['upscale', 'hdr', 'denoise'], help='Image processing mode (default: upscale)')
    parser.add_argument('--audio-mode', choices=['remove_reverb', 'enhance', 'normalize'], help='Audio processing mode (default: remove_reverb)')
    parser.add_argument('--subs-lang', type=str, default='en', help='Language code for subtitle OCR when using remove-subtitles mode (default: en)')
    parser.add_argument('--roi', type=str, default='bottom', help='Region of Interest. Presets: "bottom" (default), "top", "full". Or coords "x,y,w,h" (0.0-1.0).')
    parser.add_argument('--strict', action='store_true', help='Strict mode')
    parser.add_argument('--allow-fallback', action='store_true', help='Allow ffmpeg fallback when RIFE is not available (default: disabled)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose')
    parser.add_argument('--job', '-j', help='Job id (override)')

    args = parser.parse_args()

    # Setup logging
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logger('pipeline', level=log_level)

    logger = get_logger(__name__)
    os.environ.setdefault('USE_NATIVE_PROCESSORS', '1')
    try:
        config_loader = ConfigLoader(config_path=args.config)
        # Pass CLI-provided input as an override so loader validation accepts it
        overrides = {}
        if args.input:
            overrides['input_url'] = args.input
        if getattr(args, 'job', None):
            overrides['job_id'] = args.job
        config = config_loader.load(overrides=overrides)

        # CLI-level overrides: allow explicit bucket to override env/config
        if getattr(args, 'bucket', None):
            config.b2_bucket = args.bucket

        # Allow passing B2 credentials/endpoint from CLI so user doesn't need to set env
        if getattr(args, 'b2_key', None):
            config.b2_key = args.b2_key
        if getattr(args, 'b2_secret', None):
            config.b2_secret = args.b2_secret
        if getattr(args, 'b2_endpoint', None):
            config.b2_endpoint = args.b2_endpoint
        if getattr(args, 'b2_region', None):
            config.b2_region = args.b2_region

        # Interpret --output as B2 target when provided:
        if args.output:
            out_str = str(args.output)
            # If user passed explicit filename -> treat as exact B2 key
            if out_str.lower().endswith('.mp4'):
                config.b2_output_key = out_str
            else:
                # Treat value as a directory/prefix on B2 bucket (no trailing slash)
                # Normalize path separators to forward slashes for S3 keys
                config.b2_output_prefix = out_str.replace('\\', '/').rstrip('/')
                # Keep local output_dir setting too for local runs
                config.output_dir = args.output

        if args.type:
            config.type = args.type
        if args.mode:
            config.mode = args.mode
        if args.scale:
            config.scale = args.scale
        if args.target_fps:
            config.target_fps = args.target_fps
        if args.prefer:
            config.prefer = args.prefer
        if getattr(args, 'strategy', None):
            config.strategy = args.strategy
        if args.strict:
            config.strict = True
        if args.image_mode:
            config.image_mode = args.image_mode
        if args.audio_mode:
            config.audio_mode = args.audio_mode

        # Subtitle language (used when mode is remove-subtitles)
        if args.subs_lang:
            config.subtitle_language = args.subs_lang
        
        # ROI configuration (Region of Interest)
        if args.roi:
            config.ROI = args.roi
            print(f"!!! FORCE OVERRIDE ROI CONFIG: {args.roi}")

        # Get git commit info
        git_commit_hash = "unknown"
        git_commit_message = "unknown"
        try:
            import subprocess
            git_hash = subprocess.check_output(
                ['git', 'rev-parse', '--short', 'HEAD'],
                stderr=subprocess.DEVNULL,
                cwd=Path(__file__).parent.parent.parent
            ).decode().strip()
            git_commit_hash = git_hash

            git_msg = subprocess.check_output(
                ['git', 'log', '-1', '--pretty=%B'],
                stderr=subprocess.DEVNULL,
                cwd=Path(__file__).parent.parent.parent
            ).decode().strip()
            git_commit_message = git_msg
        except Exception:
            pass  # Git not available or not a git repo

        logger.info("="*60)
        logger.info("Video Processing Pipeline v2.0")
        logger.info(f"Git commit: {git_commit_hash}")
        logger.info(f"Commit msg: {git_commit_message}")
        logger.info(f"Input: {config.input_url}")
        logger.info(f"Output: {getattr(config, 'output_dir', './output')}")
        logger.info(f"Mode: {config.mode}")
        logger.info("="*60)

        # Provide relevant config details to the ProcessingJob so downstream
        # orchestrator and upload helpers can make informed decisions about
        # output naming and uploads (e.g. b2_output_key, b2_bucket).
        job_id_val = config.job_id or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        job_cfg = {
            'b2_output_key': getattr(config, 'b2_output_key', None),
            'b2_output_prefix': getattr(config, 'b2_output_prefix', None),
            'b2_bucket': getattr(config, 'b2_bucket', None),
            'b2_endpoint': getattr(config, 'b2_endpoint', None),
            'b2_key': getattr(config, 'b2_key', None),
            'b2_secret': getattr(config, 'b2_secret', None),
            'b2_region': getattr(config, 'b2_region', None),
        }

        # Create unified Job
        job = Job(
            job_id=job_id_val,
            input_url=config.input_url,
            type=config.type,
            mode=config.mode,
            scale=config.scale,
            target_fps=config.target_fps,
            interp_factor=config.interp_factor,
            strategy=config.strategy,
            subtitle_language=getattr(config, 'subtitle_language', 'en'),
            audio_mode=getattr(config, 'audio_mode', 'remove_reverb'),
            image_mode=getattr(config, 'image_mode', 'upscale'),
            prefer=config.prefer,
            config=job_cfg
        )

        orchestrator = create_orchestrator_from_config(config, allow_fallback=args.allow_fallback)
        result = orchestrator.process(job)

        logger.info("="*60)
        if result.success:
            logger.info("✅ Processing completed successfully!")
            logger.info(f"Output: {result.output_path}")

            # Display upload URL if available
            upload_url = result.metrics.get('upload_url')
            if upload_url:
                logger.info("")
                logger.info("📥 Download URL:")
                logger.info(f"   {upload_url}")

            print("\n=== VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY ===\n")
            return 0
        else:
            logger.error("❌ Processing failed!")
            for error in result.errors:
                logger.error(f"  - {error}")
            return 1

    except DomainException as e:
        logger.error(f"Pipeline error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 130
    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
