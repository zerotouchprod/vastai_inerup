"""
Audio preservation module for video processing pipeline.
Extracts and merges audio tracks to prevent audio loss during frame-based processing.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any
import ffmpeg

logger = logging.getLogger(__name__)


class AudioProcessingError(Exception):
    """Raised when audio processing fails."""
    pass


class AudioPreserver:
    """
    Handles audio track extraction and merging for video processing.

    The video processing pipeline works on individual frames, which loses audio.
    This class extracts audio before processing and merges it back after.

    Usage:
        preserver = AudioPreserver()

        # Extract audio before processing
        audio_path = preserver.extract_audio(input_video, "temp_audio.aac")

        # ... process video frames ...

        # Merge audio back
        preserver.merge_audio_video(processed_video, audio_path, final_output)
    """

    def __init__(self,
                 audio_codec: str = 'aac',
                 audio_bitrate: str = '192k',
                 fallback_to_silent: bool = True):
        """
        Initialize audio preserver.

        Args:
            audio_codec: Output audio codec (default: 'aac')
            audio_bitrate: Audio bitrate (default: '192k')
            fallback_to_silent: Create silent video if audio fails (default: True)
        """
        self.audio_codec = audio_codec
        self.audio_bitrate = audio_bitrate
        self.fallback_to_silent = fallback_to_silent

        logger.info(f"AudioPreserver initialized (codec={audio_codec}, bitrate={audio_bitrate})")

    def extract_audio(self, video_path: Path, output_path: Path) -> bool:
        """
        Extract audio track from video file.

        Args:
            video_path: Path to input video file
            output_path: Path to save extracted audio

        Returns:
            True if audio extracted successfully, False if no audio track

        Raises:
            AudioProcessingError: If extraction fails with error
        """
        try:
            logger.info(f"Extracting audio from {video_path}")

            # Get video info first to check if audio exists
            probe = ffmpeg.probe(str(video_path))
            audio_streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']

            if not audio_streams:
                logger.warning(f"No audio track found in {video_path}")
                return False

            # Log audio info
            audio_info = audio_streams[0]
            codec = audio_info.get('codec_name', 'unknown')
            duration = float(audio_info.get('duration', 0))
            bitrate = int(audio_info.get('bit_rate', 0)) // 1000 if 'bit_rate' in audio_info else 0

            logger.info(f"Audio track detected: codec={codec}, duration={duration:.2f}s, bitrate={bitrate}kbps")

            # Extract audio stream
            stream = ffmpeg.input(str(video_path))
            audio = stream.audio
            output = ffmpeg.output(audio, str(output_path), acodec='copy')

            # Run extraction
            ffmpeg.run(output, capture_stdout=True, capture_stderr=True, overwrite_output=True)

            logger.info(f"Audio extracted successfully to {output_path}")
            return True

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"FFmpeg error during audio extraction: {error_msg}")
            raise AudioProcessingError(f"Failed to extract audio: {error_msg}")
        except Exception as e:
            logger.error(f"Unexpected error during audio extraction: {e}")
            raise AudioProcessingError(f"Unexpected error: {e}")

    def merge_audio_video(self,
                         video_path: Path,
                         audio_path: Path,
                         output_path: Path,
                         video_codec: str = 'copy') -> bool:
        """
        Merge audio track with processed video.

        Args:
            video_path: Path to video file (without audio)
            audio_path: Path to audio file to merge
            output_path: Path to save final video with audio
            video_codec: Video codec ('copy' to avoid re-encoding, default: 'copy')

        Returns:
            True if merge successful, False otherwise

        Raises:
            AudioProcessingError: If merge fails
        """
        try:
            logger.info(f"Merging audio into video: {video_path} + {audio_path} -> {output_path}")

            # Check inputs exist
            if not video_path.exists():
                raise AudioProcessingError(f"Video file not found: {video_path}")
            if not audio_path.exists():
                raise AudioProcessingError(f"Audio file not found: {audio_path}")

            # Load video and audio streams
            video = ffmpeg.input(str(video_path))
            audio = ffmpeg.input(str(audio_path))

            # Merge streams
            output = ffmpeg.output(
                video.video,  # Video stream
                audio.audio,  # Audio stream
                str(output_path),
                vcodec=video_codec,      # Don't re-encode video (fast)
                acodec=self.audio_codec, # Re-encode audio to target codec
                audio_bitrate=self.audio_bitrate,
                shortest=None            # Match shortest stream duration
            )

            # Run merge
            ffmpeg.run(output, capture_stdout=True, capture_stderr=True, overwrite_output=True)

            logger.info(f"Audio merged successfully: {output_path}")
            return True

        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"FFmpeg error during audio merge: {error_msg}")
            raise AudioProcessingError(f"Failed to merge audio: {error_msg}")
        except Exception as e:
            logger.error(f"Unexpected error during audio merge: {e}")
            raise AudioProcessingError(f"Unexpected error: {e}")

    def get_audio_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Get audio stream information from file.

        Args:
            file_path: Path to video/audio file

        Returns:
            Dict with audio info, or None if no audio track
        """
        try:
            probe = ffmpeg.probe(str(file_path))
            audio_streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']

            if not audio_streams:
                return None

            audio = audio_streams[0]
            return {
                'codec': audio.get('codec_name'),
                'duration': float(audio.get('duration', 0)),
                'sample_rate': int(audio.get('sample_rate', 0)),
                'channels': int(audio.get('channels', 0)),
                'bitrate': int(audio.get('bit_rate', 0)) // 1000 if 'bit_rate' in audio else None
            }
        except Exception as e:
            logger.warning(f"Failed to get audio info from {file_path}: {e}")
            return None

    def has_audio_track(self, video_path: Path) -> bool:
        """
        Check if video file has audio track.

        Args:
            video_path: Path to video file

        Returns:
            True if audio track exists, False otherwise
        """
        return self.get_audio_info(video_path) is not None


# Convenience functions
def extract_audio(video_path: Path, output_path: Path) -> bool:
    """Extract audio from video (convenience function)."""
    preserver = AudioPreserver()
    return preserver.extract_audio(video_path, output_path)


def merge_audio_video(video_path: Path, audio_path: Path, output_path: Path) -> bool:
    """Merge audio with video (convenience function)."""
    preserver = AudioPreserver()
    return preserver.merge_audio_video(video_path, audio_path, output_path)


def has_audio(video_path: Path) -> bool:
    """Check if video has audio track (convenience function)."""
    preserver = AudioPreserver()
    return preserver.has_audio_track(video_path)

