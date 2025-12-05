"""Test that upscale mode preserves original FPS."""
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import tempfile
import shutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from domain.models import ProcessingJob
from application.orchestrator import VideoProcessingOrchestrator


def test_upscale_fps_preserved():
    """Test that upscale mode uses original video FPS, not job.target_fps."""

    # Mock all dependencies
    downloader = Mock()
    extractor = Mock()
    upscaler = Mock()
    interpolator = Mock()
    assembler = Mock()
    uploader = Mock()
    logger = Mock()
    metrics = Mock()

    # Setup mock responses
    video_info = Mock()
    video_info.fps = 24.0
    video_info.frame_count = 145

    # Create a real temporary workspace
    workspace = Path(tempfile.mkdtemp(prefix="test_upscale_"))
    input_file = workspace / "input.mp4"
    frames_dir = workspace / "frames"
    upscaled_dir = workspace / "upscaled"

    # Create directories
    frames_dir.mkdir(exist_ok=True)
    upscaled_dir.mkdir(exist_ok=True)

    # Create dummy frame files
    frames = []
    for i in range(1, 146):
        frame_path = frames_dir / f"frame_{i:06d}.png"
        frame_path.touch()
        frames.append(Mock(path=frame_path))

    # Create dummy upscaled frames
    upscaled_frames = []
    for i in range(1, 146):
        upscaled_path = upscaled_dir / f"upscaled_{i:06d}.png"
        upscaled_path.touch()
        upscaled_frames.append(upscaled_path)

    downloader.download.return_value = input_file
    extractor.get_video_info.return_value = video_info
    extractor.extract_frames.return_value = frames

    # Mock upscaler to return processed frames
    upscaler_result = Mock(success=True, errors=[])
    upscaler.process.return_value = upscaler_result

    # Mock assembler to capture FPS
    assembler.assemble.return_value = workspace / "output.mp4"

    # Mock uploader
    upload_result = Mock(url="https://example.com/output.mp4")
    uploader.upload.return_value = upload_result

    # Mock metrics
    metrics.start_timer.return_value = None
    metrics.stop_timer.return_value = 100.0
    metrics.elapsed_time.return_value = 100.0
    metrics.get_summary.return_value = {}

    # Create orchestrator
    orchestrator = VideoProcessingOrchestrator(
        downloader=downloader,
        extractor=extractor,
        upscaler=upscaler,
        interpolator=interpolator,
        assembler=assembler,
        uploader=uploader,
        logger=logger,
        metrics=metrics
    )

    # Test 1: upscale mode with target_fps=60 (from config) should use original 24 FPS
    job = ProcessingJob(
        job_id="test_upscale",
        input_url="https://example.com/input.mp4",
        mode="upscale",
        scale=2.0,
        target_fps=60,  # This should be IGNORED for upscale
        interp_factor=2.5
    )

    # Patch tempfile.mkdtemp to return our workspace
    with patch('tempfile.mkdtemp', return_value=str(workspace)):
        try:
            result = orchestrator.process(job)

            # Check that assembler was called with original FPS (24), not target_fps (60)
            assembler.assemble.assert_called_once()
            call_args = assembler.assemble.call_args

            # Extract fps from call
            fps_used = call_args.kwargs.get('fps')

            print(f"✓ Test 1: Upscale with target_fps=60")
            print(f"  Video FPS: {video_info.fps}")
            print(f"  Job target_fps: {job.target_fps} (should be IGNORED)")
            print(f"  FPS passed to assembler: {fps_used}")
            print(f"  Expected: {video_info.fps}")

            assert fps_used == 24.0, f"Expected FPS=24.0 for upscale, got {fps_used}"
            print(f"  ✅ PASS: Upscale correctly uses original FPS ({video_info.fps})")

        finally:
            # Cleanup
            if workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

    # Test 2: interp mode should use target_fps or calculate from interp_factor
    assembler.reset_mock()

    # Create new workspace for test 2
    workspace2 = Path(tempfile.mkdtemp(prefix="test_interp_"))
    interp_dir = workspace2 / "interpolated"
    interp_dir.mkdir(exist_ok=True)
    
    # Create dummy interpolated frames
    for i in range(1, 291):  # 145 * 2 = 290 frames
        interp_path = interp_dir / f"interp_{i:06d}.png"
        interp_path.touch()

    job2 = ProcessingJob(
        job_id="test_interp",
        input_url="https://example.com/input.mp4",
        mode="interp",
        target_fps=None,  # Not set, should calculate from interp_factor
        interp_factor=2.0
    )

    interpolator_result = Mock(success=True, errors=[])
    interpolator.process.return_value = interpolator_result

    with patch('tempfile.mkdtemp', return_value=str(workspace2)):
        try:
            result = orchestrator.process(job2)

            assembler.assemble.assert_called_once()
            call_args = assembler.assemble.call_args
            fps_used = call_args.kwargs.get('fps')

            expected_fps = 24.0 * 2.0  # 48.0

            print(f"\n✓ Test 2: Interp with interp_factor=2.0")
            print(f"  Video FPS: {video_info.fps}")
            print(f"  Job target_fps: {job2.target_fps} (None)")
            print(f"  Job interp_factor: {job2.interp_factor}")
            print(f"  FPS passed to assembler: {fps_used}")
            print(f"  Expected: {expected_fps}")

            assert fps_used == expected_fps, f"Expected FPS={expected_fps} for interp, got {fps_used}"
            print(f"  ✅ PASS: Interp correctly calculates FPS ({expected_fps})")

        finally:
            # Cleanup
            if workspace2.exists():
                shutil.rmtree(workspace2, ignore_errors=True)

    print("\n✅ All real orchestrator tests passed!")


if __name__ == "__main__":
    test_upscale_fps_preserved()

