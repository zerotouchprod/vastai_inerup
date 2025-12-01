"""CLI interface for video processing pipeline."""

import sys
import argparse
from pathlib import Path
from datetime import datetime

from domain.models import ProcessingJob
from domain.exceptions import DomainException
from infrastructure.config import ConfigLoader
from infrastructure.io import HttpDownloader, B2S3Uploader
from infrastructure.media import FFmpegExtractor, FFmpegAssembler
from application.orchestrator import VideoProcessingOrchestrator
from application.factories import ProcessorFactory
from shared.logging import setup_logger, LoggerAdapter, get_logger
from shared.metrics import MetricsCollector


def create_orchestrator_from_config(config):
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
            interpolator = factory.create_interpolator(prefer=config.prefer)
    except Exception as e:
        if config.strict:
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
    parser.add_argument('--mode', choices=['upscale', 'interp', 'both'], help='Processing mode')
    parser.add_argument('--scale', type=float, help='Upscale factor')
    parser.add_argument('--target-fps', type=int, help='Target FPS')
    parser.add_argument('--prefer', choices=['auto', 'pytorch'], help='Backend')
    parser.add_argument('--strict', action='store_true', help='Strict mode')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose')

    args = parser.parse_args()

    # Setup logging
    import logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logger('pipeline', level=log_level)

    logger = get_logger(__name__)

    try:
        config_loader = ConfigLoader(config_path=args.config)
        config = config_loader.load()

        if args.input:
            config.input_url = args.input
        if args.mode:
            config.mode = args.mode
        if args.scale:
            config.scale = args.scale
        if args.target_fps:
            config.target_fps = args.target_fps
        if args.prefer:
            config.prefer = args.prefer
        if args.strict:
            config.strict = True

        logger.info("="*60)
        logger.info("Video Processing Pipeline v2.0")
        logger.info(f"Input: {config.input_url}")
        logger.info(f"Mode: {config.mode}")
        logger.info("="*60)

        job = ProcessingJob(
            job_id=config.job_id or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            input_url=config.input_url,
            mode=config.mode,
            scale=config.scale,
            target_fps=config.target_fps,
            interp_factor=config.interp_factor,
            prefer=config.prefer,
            strategy=config.strategy,
            config={}
        )

        orchestrator = create_orchestrator_from_config(config)
        result = orchestrator.process(job)

        logger.info("="*60)
        if result.success:
            logger.info("✅ Processing completed successfully!")
            logger.info(f"Output: {result.output_path}")
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
