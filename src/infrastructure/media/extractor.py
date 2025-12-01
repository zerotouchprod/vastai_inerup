"""Frame extractor implementation."""

from pathlib import Path
from typing import List

from domain.protocols import IExtractor
from domain.models import Video, Frame
from domain.exceptions import ExtractionError
from shared.logging import get_logger
from infrastructure.media.ffmpeg import FFmpegWrapper

logger = get_logger(__name__)


class FFmpegExtractor:
    """
    Extracts frames from video using FFmpeg.
    Implements IExtractor protocol.
    """

    def __init__(self):
        self._ffmpeg = FFmpegWrapper()
        self._logger = get_logger(__name__)

    def get_video_info(self, video_path: Path) -> Video:
        """
        Get metadata about a video file.

        Args:
            video_path: Path to video file

        Returns:
            Video model with metadata

        Raises:
            ExtractionError: If metadata extraction fails
        """
        if not video_path.exists():
            raise ExtractionError(f"Video file not found: {video_path}")

        try:
            info = self._ffmpeg.get_video_info(video_path)
            fps = self._ffmpeg.get_fps(video_path)
            duration = self._ffmpeg.get_duration(video_path)

            width = int(info.get('width', 0))
            height = int(info.get('height', 0))
            frame_count = int(info.get('nb_frames', 0))
            codec = info.get('codec_name', 'unknown')

            # Calculate frame count if not available
            if frame_count == 0 and duration > 0 and fps > 0:
                frame_count = int(duration * fps)

            return Video(
                path=video_path,
                fps=fps,
                duration=duration,
                width=width,
                height=height,
                frame_count=frame_count,
                codec=codec
            )

        except Exception as e:
            raise ExtractionError(f"Failed to get video info: {e}")

    def get_fps(self, video_path: Path) -> float:
        """Get frames per second of a video."""
        return self._ffmpeg.get_fps(video_path)

    def get_duration(self, video_path: Path) -> float:
        """Get duration of a video in seconds."""
        return self._ffmpeg.get_duration(video_path)

    def extract_frames(self, video: Video, output_dir: Path) -> List[Frame]:
        """
        Extract frames from video to output directory.

        Args:
            video: Video model
            output_dir: Directory to save frames

        Returns:
            List of Frame objects

        Raises:
            ExtractionError: If extraction fails
        """
        self._logger.info(
            f"Extracting frames from {video.path} ({video.frame_count} frames)"
        )

        frame_paths = self._ffmpeg.extract_frames(
            video.path,
            output_dir,
            pattern="frame_%06d.png"
        )

        # Create Frame objects
        frames = []
        for i, frame_path in enumerate(frame_paths):
            timestamp = i / video.fps if video.fps > 0 else 0.0
            frames.append(Frame(
                path=frame_path,
                index=i,
                timestamp=timestamp
            ))

        self._logger.info(f"Extracted {len(frames)} frames to {output_dir}")
        return frames

