"""
Pytest configuration and fixtures for video processing tests.
Provides reusable fixtures for video files, configs, and test utilities.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
from typing import Generator

# Import test video generator
import sys
sys.path.insert(0, str(Path(__file__).parent))
from fixtures.generate_synthetic_videos import (
    generate_test_video_with_audio,
    generate_silent_video
)


@pytest.fixture(scope="session")
def test_videos_dir() -> Path:
    """Directory containing test video fixtures."""
    return Path(__file__).parent / "fixtures" / "videos"


@pytest.fixture(scope="session")
def sample_video_with_audio(test_videos_dir: Path) -> Generator[Path, None, None]:
    """
    Sample video with audio track (5 seconds, 640x480, 24fps).
    Generated once per test session.
    """
    video_path = test_videos_dir / "sample_with_audio.mp4"

    # Generate if doesn't exist
    if not video_path.exists():
        test_videos_dir.mkdir(parents=True, exist_ok=True)
        generate_test_video_with_audio(video_path, duration=5.0)

    yield video_path

    # Cleanup after session (optional - keep for reuse)
    # if video_path.exists():
    #     video_path.unlink()


@pytest.fixture(scope="session")
def sample_silent_video(test_videos_dir: Path) -> Generator[Path, None, None]:
    """Sample video without audio track (3 seconds)."""
    video_path = test_videos_dir / "sample_silent.mp4"

    if not video_path.exists():
        test_videos_dir.mkdir(parents=True, exist_ok=True)
        generate_silent_video(video_path, duration=3.0)

    yield video_path


@pytest.fixture(scope="session")
def sample_video_with_subtitles(test_videos_dir: Path) -> Generator[Path, None, None]:
    """Sample video with hardcoded subtitles."""
    video_path = test_videos_dir / "sample_subtitles.mp4"

    if not video_path.exists():
        test_videos_dir.mkdir(parents=True, exist_ok=True)
        generate_test_video_with_audio(
            video_path,
            duration=5.0,
            with_subtitle=True,
            subtitle_text="TEST SUBTITLE"
        )

    yield video_path


@pytest.fixture(scope="session")
def sample_short_video(test_videos_dir: Path) -> Generator[Path, None, None]:
    """Short video for quick tests (2 seconds, 320x240)."""
    video_path = test_videos_dir / "sample_short.mp4"

    if not video_path.exists():
        test_videos_dir.mkdir(parents=True, exist_ok=True)
        generate_test_video_with_audio(
            video_path,
            duration=2.0,
            fps=24,
            width=320,
            height=240
        )

    yield video_path


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Temporary workspace for test operations."""
    workspace = Path(tempfile.mkdtemp(prefix="test_workspace_"))
    yield workspace

    # Cleanup
    if workspace.exists():
        shutil.rmtree(workspace)


@pytest.fixture
def performance_baseline() -> dict:
    """
    Performance baselines for regression testing.
    These values are based on Sprint 1 measurements.
    """
    return {
        'ocr_time_per_frame_ms': 150,  # 150ms per frame (with ROI optimization)
        'inpainting_time_per_frame_s': 2.0,  # 2s per frame (ProPainter)
        'audio_extraction_time_s': 2.0,  # 2s for extraction
        'audio_merge_time_s': 3.0,  # 3s for merging
        'memory_peak_mb': 1300,  # 1.3GB peak memory
        'total_overhead_s': 5.0,  # 5s overhead for audio preservation
    }


@pytest.fixture
def quality_thresholds() -> dict:
    """
    Quality metric thresholds for acceptance testing.
    """
    return {
        'psnr_min': 40.0,  # PSNR should be > 40dB in non-processed regions
        'ssim_min': 0.95,  # SSIM should be > 0.95 in non-processed regions
        'audio_duration_tolerance_s': 0.1,  # Audio duration tolerance
    }


# Markers for different test categories
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "real_world: marks tests using real downloaded videos"
    )
    config.addinivalue_line(
        "markers", "integration: marks integration tests"
    )
    config.addinivalue_line(
        "markers", "benchmark: marks performance benchmark tests"
    )
    config.addinivalue_line(
        "markers", "quality: marks quality metric tests"
    )

