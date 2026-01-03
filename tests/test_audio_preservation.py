"""
Unit tests for audio preservation functionality.
Tests audio extraction, merging, and error handling.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import ffmpeg

from src.infrastructure.video.audio_handler import (
    AudioPreserver, AudioProcessingError, extract_audio, merge_audio_video, has_audio
)


class TestAudioPreserver:
    """Test AudioPreserver class."""

    def test_init_default_params(self):
        """Test initialization with default parameters."""
        preserver = AudioPreserver()

        assert preserver.audio_codec == 'aac'
        assert preserver.audio_bitrate == '192k'
        assert preserver.fallback_to_silent is True

    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        preserver = AudioPreserver(
            audio_codec='mp3',
            audio_bitrate='128k',
            fallback_to_silent=False
        )

        assert preserver.audio_codec == 'mp3'
        assert preserver.audio_bitrate == '128k'
        assert preserver.fallback_to_silent is False

    @patch('ffmpeg.probe')
    @patch('ffmpeg.input')
    @patch('ffmpeg.output')
    @patch('ffmpeg.run')
    def test_extract_audio_success(self, mock_run, mock_output, mock_input, mock_probe):
        """Test successful audio extraction."""
        # Mock probe to return audio stream
        mock_probe.return_value = {
            'streams': [
                {
                    'codec_type': 'audio',
                    'codec_name': 'aac',
                    'duration': '120.5',
                    'bit_rate': '192000'
                }
            ]
        }

        # Mock ffmpeg chain
        mock_stream = MagicMock()
        mock_input.return_value = mock_stream
        mock_stream.audio = MagicMock()

        preserver = AudioPreserver()
        video_path = Path("test_video.mp4")
        audio_path = Path("test_audio.aac")

        result = preserver.extract_audio(video_path, audio_path)

        assert result is True
        mock_probe.assert_called_once()
        mock_run.assert_called_once()

    @patch('ffmpeg.probe')
    def test_extract_audio_no_audio_track(self, mock_probe):
        """Test extraction when video has no audio track."""
        # Mock probe to return no audio streams
        mock_probe.return_value = {
            'streams': [
                {'codec_type': 'video'}
            ]
        }

        preserver = AudioPreserver()
        video_path = Path("test_video.mp4")
        audio_path = Path("test_audio.aac")

        result = preserver.extract_audio(video_path, audio_path)

        assert result is False

    @patch('ffmpeg.probe')
    @patch('ffmpeg.input')
    @patch('ffmpeg.output')
    @patch('ffmpeg.run')
    def test_extract_audio_ffmpeg_error(self, mock_run, mock_output, mock_input, mock_probe):
        """Test extraction when FFmpeg fails."""
        mock_probe.return_value = {
            'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}]
        }

        # Mock FFmpeg error
        error = ffmpeg.Error('ffmpeg', '', b'Error message')
        mock_run.side_effect = error

        preserver = AudioPreserver()
        video_path = Path("test_video.mp4")
        audio_path = Path("test_audio.aac")

        with pytest.raises(AudioProcessingError):
            preserver.extract_audio(video_path, audio_path)

    @patch('ffmpeg.input')
    @patch('ffmpeg.output')
    @patch('ffmpeg.run')
    def test_merge_audio_video_success(self, mock_run, mock_output, mock_input, tmp_path):
        """Test successful audio/video merging."""
        # Create temporary files
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "audio.aac"
        output_path = tmp_path / "final.mp4"

        video_path.touch()
        audio_path.touch()

        # Mock ffmpeg chain
        mock_video_stream = MagicMock()
        mock_audio_stream = MagicMock()

        def input_side_effect(path):
            if 'video' in path:
                return mock_video_stream
            return mock_audio_stream

        mock_input.side_effect = input_side_effect
        mock_video_stream.video = MagicMock()
        mock_audio_stream.audio = MagicMock()

        preserver = AudioPreserver()
        result = preserver.merge_audio_video(video_path, audio_path, output_path)

        assert result is True
        mock_run.assert_called_once()

    def test_merge_audio_video_missing_video(self, tmp_path):
        """Test merge fails when video file missing."""
        video_path = tmp_path / "nonexistent.mp4"
        audio_path = tmp_path / "audio.aac"
        output_path = tmp_path / "final.mp4"

        audio_path.touch()

        preserver = AudioPreserver()

        with pytest.raises(AudioProcessingError, match="Video file not found"):
            preserver.merge_audio_video(video_path, audio_path, output_path)

    def test_merge_audio_video_missing_audio(self, tmp_path):
        """Test merge fails when audio file missing."""
        video_path = tmp_path / "video.mp4"
        audio_path = tmp_path / "nonexistent.aac"
        output_path = tmp_path / "final.mp4"

        video_path.touch()

        preserver = AudioPreserver()

        with pytest.raises(AudioProcessingError, match="Audio file not found"):
            preserver.merge_audio_video(video_path, audio_path, output_path)

    @patch('ffmpeg.probe')
    def test_get_audio_info_with_audio(self, mock_probe):
        """Test getting audio info from file with audio."""
        mock_probe.return_value = {
            'streams': [
                {
                    'codec_type': 'audio',
                    'codec_name': 'aac',
                    'duration': '120.5',
                    'sample_rate': '48000',
                    'channels': '2',
                    'bit_rate': '192000'
                }
            ]
        }

        preserver = AudioPreserver()
        info = preserver.get_audio_info(Path("test.mp4"))

        assert info is not None
        assert info['codec'] == 'aac'
        assert info['duration'] == 120.5
        assert info['sample_rate'] == 48000
        assert info['channels'] == 2
        assert info['bitrate'] == 192

    @patch('ffmpeg.probe')
    def test_get_audio_info_no_audio(self, mock_probe):
        """Test getting audio info from file without audio."""
        mock_probe.return_value = {
            'streams': [{'codec_type': 'video'}]
        }

        preserver = AudioPreserver()
        info = preserver.get_audio_info(Path("test.mp4"))

        assert info is None

    @patch('ffmpeg.probe')
    def test_has_audio_track_true(self, mock_probe):
        """Test has_audio_track returns True when audio exists."""
        mock_probe.return_value = {
            'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}]
        }

        preserver = AudioPreserver()
        result = preserver.has_audio_track(Path("test.mp4"))

        assert result is True

    @patch('ffmpeg.probe')
    def test_has_audio_track_false(self, mock_probe):
        """Test has_audio_track returns False when no audio."""
        mock_probe.return_value = {
            'streams': [{'codec_type': 'video'}]
        }

        preserver = AudioPreserver()
        result = preserver.has_audio_track(Path("test.mp4"))

        assert result is False


class TestConvenienceFunctions:
    """Test convenience wrapper functions."""

    @patch.object(AudioPreserver, 'extract_audio')
    def test_extract_audio_wrapper(self, mock_extract):
        """Test extract_audio convenience function."""
        mock_extract.return_value = True

        result = extract_audio(Path("video.mp4"), Path("audio.aac"))

        assert result is True
        mock_extract.assert_called_once()

    @patch.object(AudioPreserver, 'merge_audio_video')
    def test_merge_audio_video_wrapper(self, mock_merge):
        """Test merge_audio_video convenience function."""
        mock_merge.return_value = True

        result = merge_audio_video(
            Path("video.mp4"),
            Path("audio.aac"),
            Path("final.mp4")
        )

        assert result is True
        mock_merge.assert_called_once()

    @patch.object(AudioPreserver, 'has_audio_track')
    def test_has_audio_wrapper(self, mock_has_audio):
        """Test has_audio convenience function."""
        mock_has_audio.return_value = True

        result = has_audio(Path("video.mp4"))

        assert result is True
        mock_has_audio.assert_called_once()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

