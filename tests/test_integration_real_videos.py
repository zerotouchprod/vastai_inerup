"""
Integration tests for video processing pipeline with real videos.
Tests end-to-end processing with quality validation.
"""

import pytest
from pathlib import Path
import time
import sys

# Add tests/utils to path
sys.path.insert(0, str(Path(__file__).parent.parent / "utils"))
from quality_metrics import (
    compare_videos_quality,
    compare_audio_duration,
    validate_video_quality
)

from src.domain.models import Job
from src.application.factories import ProcessorFactory
from src.application.orchestrator import VideoProcessingOrchestrator
from src.infrastructure.http.downloader import HttpDownloader
from src.infrastructure.storage.b2_uploader import DummyUploader
from src.infrastructure.video.ffmpeg_wrapper import FFmpegExtractor, FFmpegAssembler
from src.shared.logging import LoggerAdapter, get_logger
from src.infrastructure.metrics.collector import MetricsCollector


class TestVideoProcessingIntegration:
    """Integration tests for complete video processing pipeline."""

    @pytest.fixture
    def orchestrator(self, temp_workspace):
        """Create orchestrator for testing."""
        factory = ProcessorFactory()

        return VideoProcessingOrchestrator(
            downloader=HttpDownloader(),
            extractor=FFmpegExtractor(),
            assembler=FFmpegAssembler(),
            uploader=DummyUploader(),
            upscaler=None,
            interpolator=None,
            subtitle_remover=None,
            logger=LoggerAdapter(get_logger(__name__)),
            metrics=MetricsCollector()
        )

    @pytest.mark.integration
    def test_audio_preservation_with_synthetic_video(
        self, sample_video_with_audio, temp_workspace, orchestrator
    ):
        """Test that audio is preserved through processing pipeline."""
        # Create job
        job = Job(
            job_id="test_audio_001",
            input_url=str(sample_video_with_audio),
            type='video',
            mode='upscale',  # Simple mode for testing
            scale=1.0  # No actual upscaling
        )

        # Process
        result = orchestrator.process(job)

        # Validate
        assert result.success, f"Processing failed: {result.errors}"
        assert result.output_path.exists()

        # Check audio preservation
        audio_comparison = compare_audio_duration(
            sample_video_with_audio,
            result.output_path
        )

        assert audio_comparison['original_has_audio'], "Original should have audio"
        assert audio_comparison['processed_has_audio'], "Processed should have audio"
        assert audio_comparison['duration_match'], \
            f"Audio duration mismatch: {audio_comparison.get('duration_diff', 'N/A')}s"

    @pytest.mark.integration
    def test_silent_video_handling(
        self, sample_silent_video, temp_workspace, orchestrator
    ):
        """Test that silent videos are processed correctly."""
        job = Job(
            job_id="test_silent_001",
            input_url=str(sample_silent_video),
            type='video',
            mode='upscale',
            scale=1.0
        )

        result = orchestrator.process(job)

        assert result.success
        assert result.output_path.exists()

        # Silent video should remain silent (no audio track)
        audio_comparison = compare_audio_duration(
            sample_silent_video,
            result.output_path
        )

        assert not audio_comparison['original_has_audio']
        assert not audio_comparison['processed_has_audio']

    @pytest.mark.integration
    @pytest.mark.quality
    def test_video_quality_preservation(
        self, sample_short_video, temp_workspace, orchestrator, quality_thresholds
    ):
        """Test that video quality is preserved in non-processed regions."""
        job = Job(
            job_id="test_quality_001",
            input_url=str(sample_short_video),
            type='video',
            mode='upscale',
            scale=1.0
        )

        result = orchestrator.process(job)

        assert result.success

        # Compare quality in top 70% of frame (non-subtitle region)
        # ROI: (x=0, y=0, w=full, h=70%)
        cap = cv2.VideoCapture(str(sample_short_video))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()

        roi = (0, 0, width, int(height * 0.7))

        passed, metrics = validate_video_quality(
            sample_short_video,
            result.output_path,
            psnr_threshold=quality_thresholds['psnr_min'],
            ssim_threshold=quality_thresholds['ssim_min'],
            roi=roi
        )

        assert passed, \
            f"Quality validation failed: PSNR={metrics.get('psnr_mean', 0):.2f}dB, " \
            f"SSIM={metrics.get('ssim_mean', 0):.3f}"

    @pytest.mark.integration
    @pytest.mark.slow
    def test_subtitle_removal_preserves_audio(
        self, sample_video_with_subtitles, temp_workspace
    ):
        """Test that subtitle removal preserves audio."""
        from src.infrastructure.processors.subtitle.wrapper import SubtitleRemoverProPainterWrapper

        # Check if subtitle remover is available
        if not SubtitleRemoverProPainterWrapper.is_available():
            pytest.skip("ProPainter not available")

        factory = ProcessorFactory()
        subtitle_remover = factory.create_subtitle_remover(
            prefer='propainter',
            lang='en',
            roi='bottom'
        )

        # Create frames directory
        frames_dir = temp_workspace / "frames"
        output_dir = temp_workspace / "output"
        frames_dir.mkdir()
        output_dir.mkdir()

        # Extract frames
        from src.infrastructure.video.ffmpeg_wrapper import FFmpegExtractor
        extractor = FFmpegExtractor()
        video_info = extractor.get_video_info(sample_video_with_subtitles)
        frame_paths = extractor.extract_frames(video_info, frames_dir)

        # Process
        result = subtitle_remover.process(frame_paths, output_dir)

        assert result.success

        # TODO: Assemble video and check audio preservation
        # This requires full pipeline integration


class TestPerformanceBenchmarks:
    """Performance benchmarks for regression testing."""

    @pytest.mark.benchmark
    def test_audio_extraction_performance(
        self, sample_video_with_audio, temp_workspace, performance_baseline, benchmark
    ):
        """Benchmark audio extraction time."""
        from src.infrastructure.video.audio_handler import AudioPreserver

        preserver = AudioPreserver()
        audio_path = temp_workspace / "test_audio.aac"

        # Benchmark
        result = benchmark(preserver.extract_audio, sample_video_with_audio, audio_path)

        assert result is True

        # Check against baseline (allow 50% margin)
        baseline_ms = performance_baseline['audio_extraction_time_s'] * 1000
        actual_ms = benchmark.stats['mean'] * 1000

        assert actual_ms < baseline_ms * 1.5, \
            f"Audio extraction too slow: {actual_ms:.0f}ms (baseline: {baseline_ms:.0f}ms)"

    @pytest.mark.benchmark
    def test_audio_merge_performance(
        self, sample_video_with_audio, temp_workspace, performance_baseline, benchmark
    ):
        """Benchmark audio merging time."""
        from src.infrastructure.video.audio_handler import AudioPreserver

        preserver = AudioPreserver()

        # Setup: extract audio first
        audio_path = temp_workspace / "audio.aac"
        preserver.extract_audio(sample_video_with_audio, audio_path)

        output_path = temp_workspace / "merged.mp4"

        # Benchmark merge
        result = benchmark(
            preserver.merge_audio_video,
            sample_video_with_audio,
            audio_path,
            output_path
        )

        assert result is True

        # Check against baseline
        baseline_ms = performance_baseline['audio_merge_time_s'] * 1000
        actual_ms = benchmark.stats['mean'] * 1000

        assert actual_ms < baseline_ms * 1.5, \
            f"Audio merge too slow: {actual_ms:.0f}ms (baseline: {baseline_ms:.0f}ms)"


class TestQualityMetrics:
    """Test quality metric calculations."""

    @pytest.mark.quality
    def test_psnr_calculation_identical_images(self):
        """Test PSNR with identical images (should be infinite)."""
        import numpy as np
        from quality_metrics import calculate_psnr

        img = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

        psnr = calculate_psnr(img, img)

        assert psnr > 100 or psnr == float('inf'), "Identical images should have very high PSNR"

    @pytest.mark.quality
    def test_ssim_calculation_identical_images(self):
        """Test SSIM with identical images (should be 1.0)."""
        import numpy as np
        from quality_metrics import calculate_ssim

        img = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

        ssim = calculate_ssim(img, img)

        assert ssim >= 0.99, f"Identical images should have SSIM ~1.0, got {ssim}"

    @pytest.mark.quality
    def test_psnr_calculation_different_images(self):
        """Test PSNR with slightly different images."""
        import numpy as np
        from quality_metrics import calculate_psnr

        img1 = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        img2 = np.clip(img1.astype(int) + 5, 0, 255).astype(np.uint8)  # Add 5 to each pixel

        psnr = calculate_psnr(img1, img2)

        assert 20 < psnr < 50, f"PSNR should be reasonable for small difference, got {psnr}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-m', 'integration'])

