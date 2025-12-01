"""
Unit tests for FFmpegAssembler.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from infrastructure.media.assembler import FFmpegAssembler
from domain.exceptions import AssemblyError


class TestFFmpegAssembler:
    """Test FFmpegAssembler class."""

    @pytest.fixture
    def assembler(self):
        """Create assembler instance."""
        with patch('infrastructure.media.assembler.FFmpegWrapper'):
            return FFmpegAssembler()

    @pytest.fixture
    def mock_frames(self, tmp_path):
        """Create mock frame files."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        frames = []
        for i in range(1, 6):
            frame = frames_dir / f"frame_{i:06d}.png"
            frame.write_text(f"frame {i}")
            frames.append(frame)

        return frames

    def test_init(self, assembler):
        """Test assembler initialization."""
        assert assembler._preferred_encoder == "h264_nvenc"
        assert assembler._fallback_encoder == "libx264"
        assert assembler._ffmpeg is not None
        assert assembler._logger is not None

    def test_supports_encoder(self, assembler):
        """Test encoder support check."""
        assembler._ffmpeg.test_encoder = Mock(return_value=True)

        result = assembler.supports_encoder("h264_nvenc")

        assert result is True
        assembler._ffmpeg.test_encoder.assert_called_once_with("h264_nvenc")

    def test_supports_encoder_not_available(self, assembler):
        """Test encoder not available."""
        assembler._ffmpeg.test_encoder = Mock(return_value=False)

        result = assembler.supports_encoder("hevc_nvenc")

        assert result is False

    def test_assemble_success(self, assembler, mock_frames, tmp_path):
        """Test successful assembly."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=24.0
        )

        assert result == output_path
        assembler._ffmpeg.assemble_video.assert_called_once()

        # Check call arguments
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['frames_dir'] == mock_frames[0].parent
        assert call_kwargs['output_path'] == output_path
        assert call_kwargs['fps'] == 24.0
        assert call_kwargs['encoder'] == "h264_nvenc"
        assert call_kwargs['pix_fmt'] == "yuv420p"

    def test_assemble_empty_frames(self, assembler, tmp_path):
        """Test assembly with empty frames list."""
        output_path = tmp_path / "output.mp4"

        with pytest.raises(AssemblyError, match="No frames to assemble"):
            assembler.assemble(
                frames=[],
                output_path=output_path,
                fps=24.0
            )

    def test_assemble_with_custom_encoder(self, assembler, mock_frames, tmp_path):
        """Test assembly with custom encoder."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=30.0,
            encoder="libx264"
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['encoder'] == "libx264"

    def test_assemble_with_custom_pattern(self, assembler, mock_frames, tmp_path):
        """Test assembly with custom frame pattern."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=24.0,
            pattern="img_%04d.jpg"
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['pattern'] == "img_%04d.jpg"

    def test_assemble_with_custom_pix_fmt(self, assembler, mock_frames, tmp_path):
        """Test assembly with custom pixel format."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=24.0,
            pix_fmt="yuv444p"
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['pix_fmt'] == "yuv444p"

    def test_assemble_nvenc_fails_fallback_to_libx264(self, assembler, mock_frames, tmp_path):
        """Test fallback to libx264 when nvenc fails."""
        output_path = tmp_path / "output.mp4"

        # First call (nvenc) fails, second call (libx264) succeeds
        assembler._ffmpeg.assemble_video = Mock(
            side_effect=[
                AssemblyError("NVENC not available"),
                output_path
            ]
        )

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=24.0
        )

        assert result == output_path
        assert assembler._ffmpeg.assemble_video.call_count == 2

        # First call with nvenc
        first_call_kwargs = assembler._ffmpeg.assemble_video.call_args_list[0][1]
        assert first_call_kwargs['encoder'] == "h264_nvenc"

        # Second call with libx264
        second_call_kwargs = assembler._ffmpeg.assemble_video.call_args_list[1][1]
        assert second_call_kwargs['encoder'] == "libx264"

    def test_assemble_both_encoders_fail(self, assembler, mock_frames, tmp_path):
        """Test when both nvenc and libx264 fail."""
        output_path = tmp_path / "output.mp4"

        # Both calls fail
        assembler._ffmpeg.assemble_video = Mock(
            side_effect=[
                AssemblyError("NVENC not available"),
                AssemblyError("libx264 failed")
            ]
        )

        with pytest.raises(AssemblyError, match="Both h264_nvenc and libx264 failed"):
            assembler.assemble(
                frames=mock_frames,
                output_path=output_path,
                fps=24.0
            )

        assert assembler._ffmpeg.assemble_video.call_count == 2

    def test_assemble_custom_encoder_fails_no_fallback(self, assembler, mock_frames, tmp_path):
        """Test that custom encoder failure doesn't trigger fallback."""
        output_path = tmp_path / "output.mp4"

        # Custom encoder fails
        assembler._ffmpeg.assemble_video = Mock(
            side_effect=AssemblyError("Custom encoder failed")
        )

        with pytest.raises(AssemblyError, match="Custom encoder failed"):
            assembler.assemble(
                frames=mock_frames,
                output_path=output_path,
                fps=24.0,
                encoder="libx265"  # Custom encoder
            )

        # Should only try once (no fallback for custom encoders)
        assert assembler._ffmpeg.assemble_video.call_count == 1

    def test_assemble_high_fps(self, assembler, mock_frames, tmp_path):
        """Test assembly with high frame rate."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=120.0
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['fps'] == 120.0

    def test_assemble_low_fps(self, assembler, mock_frames, tmp_path):
        """Test assembly with low frame rate."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=1.0
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['fps'] == 1.0

    def test_assemble_many_frames(self, assembler, tmp_path):
        """Test assembly with many frames."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        # Create 1000 frames
        frames = []
        for i in range(1, 1001):
            frame = frames_dir / f"frame_{i:06d}.png"
            frame.write_text(f"frame {i}")
            frames.append(frame)

        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=frames,
            output_path=output_path,
            fps=24.0
        )

        assert result == output_path
        # Verify it was called with the correct number of frames info
        assembler._ffmpeg.assemble_video.assert_called_once()

    def test_assemble_frames_in_subdirectory(self, assembler, tmp_path):
        """Test assembly with frames in nested directory."""
        frames_dir = tmp_path / "work" / "frames"
        frames_dir.mkdir(parents=True)

        frames = []
        for i in range(1, 6):
            frame = frames_dir / f"frame_{i:06d}.png"
            frame.write_text(f"frame {i}")
            frames.append(frame)

        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=frames,
            output_path=output_path,
            fps=24.0
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['frames_dir'] == frames_dir

    def test_assemble_all_options(self, assembler, mock_frames, tmp_path):
        """Test assembly with all custom options."""
        output_path = tmp_path / "output.mp4"
        assembler._ffmpeg.assemble_video = Mock(return_value=output_path)

        result = assembler.assemble(
            frames=mock_frames,
            output_path=output_path,
            fps=60.0,
            encoder="libx265",
            pattern="img_%05d.jpg",
            pix_fmt="yuv444p"
        )

        assert result == output_path
        call_kwargs = assembler._ffmpeg.assemble_video.call_args[1]
        assert call_kwargs['fps'] == 60.0
        assert call_kwargs['encoder'] == "libx265"
        assert call_kwargs['pattern'] == "img_%05d.jpg"
        assert call_kwargs['pix_fmt'] == "yuv444p"


class TestFFmpegAssemblerIntegration:
    """Integration tests for FFmpegAssembler (require ffmpeg)."""

    @pytest.mark.skipif(
        not Path('/usr/bin/ffmpeg').exists() and not Path('C:\\ffmpeg\\bin\\ffmpeg.exe').exists(),
        reason="FFmpeg not available"
    )
    def test_real_assembly_smoke_test(self, tmp_path):
        """Smoke test with real FFmpeg (if available)."""
        # This test is skipped if ffmpeg is not available
        # It's here as a placeholder for integration testing
        pass

