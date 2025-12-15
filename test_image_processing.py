#!/usr/bin/env python3
"""Test script for image processing functionality."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from domain.models import ImageJob
from infrastructure.io import HttpDownloader
from application.factories import ProcessorFactory
from shared.logging import setup_logger
from shared.metrics import MetricsCollector
from application.image_orchestrator import ImageProcessingOrchestrator

def test_image_processing():
    """Test image processing with local file."""
    # Setup logging
    setup_logger('test', level='INFO')
    
    # Create a dummy uploader that just saves locally
    from domain.models import UploadResult
    class LocalUploader:
        def upload(self, file_path, key):
            # Just copy to test output
            import shutil
            output_path = Path("test_output") / key
            output_path.parent.mkdir(exist_ok=True)
            shutil.copy2(file_path, output_path)
            return UploadResult(
                success=True,
                url=f"file://{output_path}",
                bucket="local",
                key=key,
                size_bytes=file_path.stat().st_size
            )
    
    # Create components
    downloader = HttpDownloader()
    factory = ProcessorFactory(use_native=True)
    
    try:
        upscaler = factory.create_upscaler(prefer='auto')
        print("✅ Upscaler created successfully")
    except Exception as e:
        print(f"❌ Failed to create upscaler: {e}")
        print("Trying with use_native=False...")
        factory = ProcessorFactory(use_native=False)
        try:
            upscaler = factory.create_upscaler(prefer='auto')
            print("✅ Upscaler created successfully (shell wrapper)")
        except Exception as e2:
            print(f"❌ Failed to create upscaler with shell wrapper: {e2}")
            return
    
    uploader = LocalUploader()
    
    # Create orchestrator
    from shared.logging import LoggerAdapter, get_logger
    logger = LoggerAdapter(get_logger('test_orchestrator'))
    metrics = MetricsCollector()
    
    orchestrator = ImageProcessingOrchestrator(
        downloader=downloader,
        upscaler=upscaler,
        uploader=uploader,
        logger=logger,
        metrics=metrics
    )
    
    # Create job for local file
    # Use file:// URL for local file
    test_image = Path("output/img1.png")
    if not test_image.exists():
        print(f"❌ Test image not found: {test_image}")
        return
    
    job = ImageJob(
        job_id="test_image_001",
        input_url=f"file://{test_image.absolute()}",
        mode="upscale",
        scale=2.0,
        prefer="auto",
        config={
            'b2_output_key': 'test_output/test_upscaled.png'
        }
    )
    
    print(f"📷 Processing image: {test_image}")
    print(f"   Scale: {job.scale}x")
    print(f"   Mode: {job.mode}")
    
    # Process
    result = orchestrator.process(job)
    
    if result.success:
        print("✅ Image processing successful!")
        print(f"   Output: {result.output_path}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
        print(f"   Upload URL: {result.metrics.get('upload_url', 'N/A')}")
    else:
        print("❌ Image processing failed!")
        for error in result.errors:
            print(f"   Error: {error}")

if __name__ == "__main__":
    test_image_processing()
