"""
Unit tests for domain models.
"""

import pytest
from pathlib import Path

from domain.models import (
    ProcessingJob,
    Video,
    UploadResult,
    ProcessingResult,
    Frame
)


class TestProcessingJob:
    """Test ProcessingJob model."""

    def test_create_valid_job(self):
        """Test creating valid job."""
        job = ProcessingJob(
            job_id="test-123",
            input_url="https://example.com/video.mp4",
            mode="upscale",
            scale=2.0
        )

        assert job.input_url == "https://example.com/video.mp4"
        assert job.mode == "upscale"
        assert job.scale == 2.0
        assert job.job_id == "test-123"

    def test_job_with_interpolation(self):
        """Test job with interpolation settings."""
        job = ProcessingJob(
            job_id="test-456",
            input_url="https://example.com/video.mp4",
            mode="interp",
            interp_factor=2.0,
            target_fps=60
        )

        assert job.mode == "interp"
        assert job.interp_factor == 2.0
        assert job.target_fps == 60

    def test_job_validation_invalid_scale(self):
        """Test job validation fails for invalid scale."""
        with pytest.raises(ValueError):
            ProcessingJob(
                job_id="test-789",
                input_url="https://example.com/video.mp4",
                mode="upscale",
                scale=-1.0  # Invalid
            )

    def test_job_validation_invalid_mode(self):
        """Test job validation fails for invalid mode."""
        with pytest.raises(ValueError):
            ProcessingJob(
                job_id="test-999",
                input_url="https://example.com/video.mp4",
                mode="invalid_mode",
                scale=2.0
            )

    def test_job_both_mode(self):
        """Test job with both upscale and interpolation."""
        job = ProcessingJob(
            job_id="test-both",
            input_url="https://example.com/video.mp4",
            mode="both",
            scale=2.0,
            interp_factor=2.0
        )

        assert job.mode == "both"
        assert job.scale == 2.0
        assert job.interp_factor == 2.0


class TestVideo:
    """Test Video model."""

    def test_create_video(self):
        """Test creating video model."""
        video = Video(
            path=Path("/tmp/video.mp4"),
            width=1920,
            height=1080,
            fps=30.0,
            duration=120.5,
            frame_count=3615,
            codec="h264"
        )

        assert video.width == 1920
        assert video.height == 1080
        assert video.fps == 30.0
        assert video.duration == 120.5
        assert video.frame_count == 3615
        assert video.codec == "h264"

    def test_video_validation_invalid_fps(self):
        """Test video validation fails for invalid fps."""
        with pytest.raises(ValueError):
            Video(
                path=Path("/tmp/video.mp4"),
                width=1920,
                height=1080,
                fps=-1.0,  # Invalid
                duration=10.0,
                frame_count=240,
                codec="h264"
            )

    def test_video_validation_invalid_dimensions(self):
        """Test video validation fails for invalid dimensions."""
        with pytest.raises(ValueError):
            Video(
                path=Path("/tmp/video.mp4"),
                width=-1920,  # Invalid
                height=1080,
                fps=30.0,
                duration=10.0,
                frame_count=300,
                codec="h264"
            )


class TestUploadResult:
    """Test UploadResult model."""

    def test_successful_upload(self):
        """Test successful upload result."""
        result = UploadResult(
            success=True,
            url="https://s3.example.com/bucket/video.mp4",
            bucket="bucket",
            key="video.mp4",
            size_bytes=1024000
        )

        assert result.success is True
        assert result.url == "https://s3.example.com/bucket/video.mp4"
        assert result.size_bytes == 1024000

    def test_failed_upload(self):
        """Test failed upload result."""
        result = UploadResult(
            success=False,
            error="Connection timeout"
        )

        assert result.success is False
        assert result.error == "Connection timeout"
        assert result.url is None


class TestProcessingResult:
    """Test ProcessingResult model."""

    def test_successful_processing(self):
        """Test successful processing result."""
        result = ProcessingResult(
            success=True,
            output_path=Path("/workspace/output.mp4"),
            duration_seconds=125.5,
            frames_processed=3000
        )

        assert result.success is True
        assert result.output_path == Path("/workspace/output.mp4")
        assert result.duration_seconds == 125.5
        assert result.frames_processed == 3000

    def test_failed_processing(self):
        """Test failed processing result."""
        result = ProcessingResult(
            success=False
        )
        result.add_error("GPU out of memory")

        assert result.success is False
        assert "GPU out of memory" in result.errors
        assert result.output_path is None

    def test_add_metrics(self):
        """Test adding metrics to result."""
        result = ProcessingResult(success=True)
        result.add_metric("fps", 30.0)
        result.add_metric("frames", 900)

        assert result.metrics["fps"] == 30.0
        assert result.metrics["frames"] == 900


class TestFrame:
    """Test Frame model."""

    def test_create_frame(self):
        """Test creating frame model."""
        frame = Frame(
            path=Path("/tmp/frames/frame_0001.png"),
            index=1,
            timestamp=0.041667
        )

        assert frame.path == Path("/tmp/frames/frame_0001.png")
        assert frame.index == 1
        assert frame.timestamp == 0.041667

    def test_frame_exists(self, tmp_path):
        """Test checking if frame exists."""
        frame_path = tmp_path / "frame_0001.png"
        frame_path.touch()

        frame = Frame(
            path=frame_path,
            index=1,
            timestamp=0.041667
        )

        assert frame.exists() is True

        # Non-existent frame
        frame2 = Frame(
            path=tmp_path / "nonexistent.png",
            index=2,
            timestamp=0.083333
        )

        assert frame2.exists() is False
