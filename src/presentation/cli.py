"""CLI interface for video processing pipeline."""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

from domain.models import ProcessingJob
from domain.exceptions import DomainException, ProcessorNotAvailableError
from infrastructure.config import ConfigLoader
from infrastructure.io import HttpDownloader, B2S3Uploader
from infrastructure.media import FFmpegExtractor, FFmpegAssembler
from application.orchestrator import VideoProcessingOrchestrator
from application.factories import ProcessorFactory
from shared.logging import setup_logger, LoggerAdapter, get_logger
from shared.metrics import MetricsCollector


def create_orchestrator_from_config(config, allow_fallback: bool = False):
    """Create orchestrator with all dependencies from config."""
    downloader = HttpDownloader()
    extractor = FFmpegExtractor()
    assembler = FFmpegAssembler()

    # Create uploader if configured
    uploader = None
    if config.b2_bucket and config.b2_key and config.b2_secret:
        uploader = B2S3Uploader(
            bucket=config.b2_bucket,
            endpoint=config.b2_endpoint or "https://s3.us-west-004.backblazeb2.com",
            access_key=config.b2_key,
            secret_key=config.b2_secret
        )
    else:
        # Dummy uploader
        from domain.models import UploadResult
        class DummyUploader:
            def upload(self, file_path, key):
                return UploadResult(success=True, url=f"file://{file_path}", bucket="local", key=key, size_bytes=0)
        uploader = DummyUploader()

    # Create processors
    factory = ProcessorFactory()
    upscaler = None
    interpolator = None

    try:
        if config.mode in ('upscale', 'both'):
            upscaler = factory.create_upscaler(prefer=config.prefer)
    except Exception as e:
        if config.strict:
            raise
        get_logger(__name__).warning(f"Upscaler not available: {e}")

    try:
        if config.mode in ('interp', 'both'):
            # Mandatory RIFE availability probe: check both native and pytorch wrappers.
            native_ok = False
            try:
                from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
                native_ok = RIFENativeWrapper.is_available()
            except Exception:
                native_ok = False

            pytorch_ok = False
            try:
                from infrastructure.processors.rife.pytorch_wrapper import RifePytorchWrapper
                pytorch_ok = RifePytorchWrapper.is_available()
            except Exception:
                pytorch_ok = False

            if not (native_ok or pytorch_ok):
                # No RIFE backend passed probe. By default (allow_fallback=False) fail early.
                msg = "No usable RIFE backend available (probe failed)"
                if config.strict or not allow_fallback:
                    raise ProcessorNotAvailableError(msg)
                get_logger(__name__).warning(msg + " — continuing because allow_fallback=True")

        if config.mode in ('interp', 'both'):
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
        metrics=metrics
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Video processing pipeline")
    parser.add_argument('--config', type=Path, help='Config YAML file')
    parser.add_argument('--input', '-i', help='Input video URL')
    parser.add_argument('--output', '-o', type=Path, help='Output directory (default: ./output)')
    parser.add_argument('--mode', choices=['upscale', 'interp', 'both'], help='Processing mode')
    parser.add_argument('--scale', type=float, help='Upscale factor')
    parser.add_argument('--target-fps', type=int, help='Target FPS')
    parser.add_argument('--prefer', choices=['auto', 'pytorch'], help='Backend')
    parser.add_argument('--strategy', choices=['interp-then-upscale', 'upscale-then-interp'], help='Processing order for "both" mode (default: interp-then-upscale)')
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

        if args.output:
            config.output_dir = args.output
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
            'b2_bucket': getattr(config, 'b2_bucket', None),
            'b2_endpoint': getattr(config, 'b2_endpoint', None),
        }

        job = ProcessingJob(
            job_id=job_id_val,
            input_url=config.input_url,
            mode=config.mode,
            scale=config.scale,
            target_fps=config.target_fps,
            interp_factor=config.interp_factor,
            prefer=config.prefer,
            strategy=config.strategy,
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
