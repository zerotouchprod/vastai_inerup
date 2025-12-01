"""
Integration tests for video processing pipeline.

These tests use real video files and test the entire pipeline end-to-end.
They are slower than unit tests but provide confidence that everything works together.

Test video: tests/video/test.mp4
- Should be a short video (5-10 seconds)
- Resolution: 640x360 or similar (for speed)
- FPS: 24 or 30

Run with:
    pytest tests/integration/ -v -s
    pytest tests/integration/test_pipeline_e2e.py::test_upscale_small_video -v
"""

import pytest
import os
from pathlib import Path
import tempfile
import shutil

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from infrastructure.config import ConfigLoader, ProcessingConfig
from application.orchestrator import VideoProcessingOrchestrator
from application.factories import ProcessorFactory
from infrastructure.io import HttpDownloader, B2S3Uploader
from infrastructure.media import FFmpegExtractor, FFmpegAssembler
from infrastructure.storage import TempStorage
from shared.logging import setup_logger, get_logger
from shared.metrics import MetricsCollector
from domain.models import ProcessingJob


# Test video path
TEST_VIDEO_DIR = Path(__file__).parent.parent / "video"
TEST_VIDEO_PATH = TEST_VIDEO_DIR / "test.mp4"


@pytest.fixture
def test_video():
    """Fixture that provides test video path."""
    if not TEST_VIDEO_PATH.exists():
        pytest.skip(f"Test video not found: {TEST_VIDEO_PATH}")
    return TEST_VIDEO_PATH


@pytest.fixture
def temp_workspace():
    """Fixture that provides temporary workspace."""
    temp_dir = tempfile.mkdtemp(prefix="pipeline_test_")
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_orchestrator(temp_workspace):
    """
    Create orchestrator with mock components for testing.
    
    Note: This uses real implementations but mocks upload to avoid B2 dependency.
    """
    # Setup logging
    logger = setup_logger("test", level="DEBUG")
    
    # Create components
    downloader = HttpDownloader()
    extractor = FFmpegExtractor()
    assembler = FFmpegAssembler()
    temp_storage = TempStorage(base_dir=temp_workspace)
    metrics = MetricsCollector()
    
    # Mock uploader (doesn't actually upload)
    class MockUploader:
        def upload(self, file_path, bucket, key, endpoint=None):
            from domain.models import UploadResult
            logger.info(f"[MOCK] Would upload {file_path} to s3://{bucket}/{key}")
            return UploadResult(
                success=True,
                url=f"https://mock.s3.example.com/{bucket}/{key}",
                bucket=bucket,
                key=key,
                size_bytes=file_path.stat().st_size if file_path.exists() else 0
            )
    
    uploader = MockUploader()
    
    # Create processor factory
    factory = ProcessorFactory()
    
    # Create orchestrator without processors (will be added in tests)
    orchestrator = VideoProcessingOrchestrator(
        downloader=downloader,
        extractor=extractor,
        upscaler=None,  # Set in test
        interpolator=None,  # Set in test
        assembler=assembler,
        uploader=uploader,
        temp_storage=temp_storage,
        logger=logger,
        metrics=metrics
    )
    
    return orchestrator, factory


class TestBasicVideoProcessing:
    """Basic tests without actual ML processing."""
    
    def test_video_info_extraction(self, test_video):
        """Test that we can extract video info."""
        from infrastructure.media import FFmpegExtractor
        
        extractor = FFmpegExtractor()
        info = extractor.get_video_info(test_video)
        
        assert info is not None
        assert info.width > 0
        assert info.height > 0
        assert info.fps > 0
        assert info.frame_count > 0
        
        print(f"\n✅ Video info: {info.width}x{info.height} @ {info.fps}fps, {info.frame_count} frames")
    
    def test_frame_extraction(self, test_video, temp_workspace):
        """Test frame extraction."""
        from infrastructure.media import FFmpegExtractor
        
        extractor = FFmpegExtractor()
        output_dir = temp_workspace / "frames"
        output_dir.mkdir()
        
        frames = extractor.extract_frames(test_video, output_dir)
        
        assert len(frames) > 0
        assert all(f.exists() for f in frames)
        
        print(f"\n✅ Extracted {len(frames)} frames")
    
    def test_frame_assembly(self, test_video, temp_workspace):
        """Test assembling frames back to video."""
        from infrastructure.media import FFmpegExtractor, FFmpegAssembler
        
        # Extract frames
        extractor = FFmpegExtractor()
        frames_dir = temp_workspace / "frames"
        frames_dir.mkdir()
        frames = extractor.extract_frames(test_video, frames_dir)
        
        # Get original FPS
        info = extractor.get_video_info(test_video)
        
        # Assemble back
        assembler = FFmpegAssembler()
        output_video = temp_workspace / "reassembled.mp4"
        
        result = assembler.assemble_video(
            frames,
            output_video,
            fps=info.fps,
            resolution=(info.width, info.height)
        )
        
        assert output_video.exists()
        assert output_video.stat().st_size > 0
        
        print(f"\n✅ Assembled video: {output_video.stat().st_size} bytes")


@pytest.mark.skipif(
    not os.getenv('RUN_ML_TESTS'),
    reason="ML tests require GPU and are slow. Set RUN_ML_TESTS=1 to run."
)
class TestMLProcessing:
    """Tests that actually use ML models (slow, requires GPU)."""
    
    def test_upscale_small_video(self, test_video, mock_orchestrator, temp_workspace):
        """Test upscaling a small video."""
        orchestrator, factory = mock_orchestrator
        
        # Try to create upscaler
        try:
            upscaler = factory.create_upscaler(prefer='pytorch')
            orchestrator._upscaler = upscaler
        except Exception as e:
            pytest.skip(f"Cannot create upscaler: {e}")
        
        # Create job
        job = ProcessingJob(
            input_url=str(test_video),
            output_dir=temp_workspace / "output",
            mode="upscale",
            scale=2.0
        )
        
        # Process
        result = orchestrator.process(job)
        
        assert result.success
        assert result.output_path.exists()
        
        print(f"\n✅ Upscaled video: {result.output_path}")
        print(f"   Processing time: {result.duration_seconds:.1f}s")
        print(f"   Frames: {result.frames_processed}")
    
    def test_interpolate_small_video(self, test_video, mock_orchestrator, temp_workspace):
        """Test interpolating a small video."""
        orchestrator, factory = mock_orchestrator
        
        # Try to create interpolator
        try:
            interpolator = factory.create_interpolator(prefer='pytorch', factor=2)
            orchestrator._interpolator = interpolator
        except Exception as e:
            pytest.skip(f"Cannot create interpolator: {e}")
        
        # Create job
        job = ProcessingJob(
            input_url=str(test_video),
            output_dir=temp_workspace / "output",
            mode="interp",
            interp_factor=2.0
        )
        
        # Process
        result = orchestrator.process(job)
        
        assert result.success
        assert result.output_path.exists()
        
        print(f"\n✅ Interpolated video: {result.output_path}")
        print(f"   Processing time: {result.duration_seconds:.1f}s")
        print(f"   Frames: {result.frames_processed}")


@pytest.mark.skipif(
    not os.getenv('RUN_FULL_TESTS'),
    reason="Full pipeline tests are very slow. Set RUN_FULL_TESTS=1 to run."
)
class TestFullPipeline:
    """Full end-to-end pipeline tests (very slow)."""
    
    def test_both_upscale_and_interpolate(self, test_video, mock_orchestrator, temp_workspace):
        """Test both upscale and interpolation together."""
        orchestrator, factory = mock_orchestrator
        
        # Create both processors
        try:
            upscaler = factory.create_upscaler(prefer='pytorch')
            interpolator = factory.create_interpolator(prefer='pytorch', factor=2)
            orchestrator._upscaler = upscaler
            orchestrator._interpolator = interpolator
        except Exception as e:
            pytest.skip(f"Cannot create processors: {e}")
        
        # Create job
        job = ProcessingJob(
            input_url=str(test_video),
            output_dir=temp_workspace / "output",
            mode="both",
            scale=2.0,
            interp_factor=2.0
        )
        
        # Process
        result = orchestrator.process(job)
        
        assert result.success
        assert result.output_path.exists()
        
        print(f"\n✅ Full pipeline completed: {result.output_path}")
        print(f"   Processing time: {result.duration_seconds:.1f}s")
        print(f"   Frames: {result.frames_processed}")


class TestDebugMode:
    """Test debug mode functionality."""
    
    def test_debug_logging_enabled(self, test_video, temp_workspace, monkeypatch):
        """Test that debug mode creates detailed logs."""
        # Enable debug mode
        monkeypatch.setenv('DEBUG_PROCESSORS', '1')
        
        from infrastructure.processors.debug import ProcessorDebugger
        
        debugger = ProcessorDebugger('test')
        assert debugger.is_enabled()
        
        # Test logging
        debugger.log_start(test_param="value")
        debugger.log_step('test_step', value=123)
        debugger.log_end(True)
        
        # Check log file exists
        assert debugger.log_file.exists()
        
        # Read and verify content
        log_content = debugger.log_file.read_text()
        assert "START: test" in log_content
        assert "test_param" in log_content
        assert "STEP: test_step" in log_content
        assert "SUCCESS" in log_content
        
        print(f"\n✅ Debug log created: {debugger.log_file}")


# Utility functions for tests
def create_test_video_if_missing():
    """
    Helper to create a test video if it doesn't exist.
    Uses ffmpeg to generate a simple test pattern.
    """
    if not TEST_VIDEO_PATH.exists():
        TEST_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        
        import subprocess
        
        # Create 5 second test video with color bars
        cmd = [
            'ffmpeg', '-f', 'lavfi',
            '-i', 'testsrc=duration=5:size=640x360:rate=24',
            '-pix_fmt', 'yuv420p',
            '-y', str(TEST_VIDEO_PATH)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            print(f"✅ Created test video: {TEST_VIDEO_PATH}")
            return True
        except Exception as e:
            print(f"❌ Failed to create test video: {e}")
            return False
    
    return True


if __name__ == '__main__':
    # Allow running this file directly to create test video
    import sys
    
    if '--create-test-video' in sys.argv:
        if create_test_video_if_missing():
            print("✅ Test video ready")
            sys.exit(0)
        else:
            print("❌ Failed to create test video")
            sys.exit(1)
    else:
        # Run tests
        pytest.main([__file__, '-v', '-s'])

