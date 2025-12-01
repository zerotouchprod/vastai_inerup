"""FFmpeg wrapper for video operations."""

import subprocess
import re
from pathlib import Path
from typing import Optional, List, Tuple

from domain.exceptions import ExtractionError, AssemblyError
from shared.logging import get_logger

logger = get_logger(__name__)


class FFmpegWrapper:
    """Low-level wrapper around ffmpeg/ffprobe commands."""

    def __init__(self):
        self._logger = get_logger(__name__)

    def get_video_info(self, video_path: Path) -> dict:
        """
        Get video metadata using ffprobe.

        Args:
            video_path: Path to video file

        Returns:
            Dictionary with video metadata

        Raises:
            ExtractionError: If ffprobe fails
        """
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,nb_frames,codec_name,duration',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1',
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            # Parse output
            info = {}
            for line in result.stdout.strip().split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key] = value

            return info

        except subprocess.CalledProcessError as e:
            raise ExtractionError(f"ffprobe failed: {e.stderr}")

    def get_fps(self, video_path: Path) -> float:
        """Get frames per second of video."""
        cmd = [
            'ffprobe',
            '-v', '0',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=avg_frame_rate',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            fps_str = result.stdout.strip()
            if '/' in fps_str:
                num, den = fps_str.split('/')
                return float(num) / float(den)
            return float(fps_str)

        except Exception as e:
            raise ExtractionError(f"Failed to get FPS: {e}")

    def get_duration(self, video_path: Path) -> float:
        """Get duration of video in seconds."""
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(video_path)
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            duration_str = result.stdout.strip()
            return float(duration_str) if duration_str else 0.0

        except Exception as e:
            self._logger.warning(f"Failed to get duration: {e}")
            return 0.0

    def extract_frames(
        self,
        video_path: Path,
        output_dir: Path,
        pattern: str = "frame_%06d.png"
    ) -> List[Path]:
        """
        Extract all frames from video.

        Args:
            video_path: Path to video file
            output_dir: Directory to save frames
            pattern: Filename pattern for frames

        Returns:
            List of frame file paths

        Raises:
            ExtractionError: If extraction fails
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = output_dir / pattern

        cmd = [
            'ffmpeg',
            '-y',
            '-i', str(video_path),
            '-pix_fmt', 'rgb24',
            '-vf', 'format=rgb24',  # Force 8-bit RGB output
            str(output_pattern)
        ]

        self._logger.info(f"Extracting frames to {output_dir}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            # List extracted frames
            frames = sorted(output_dir.glob("frame_*.png"))
            self._logger.info(f"Extracted {len(frames)} frames")

            return frames

        except subprocess.CalledProcessError as e:
            raise ExtractionError(f"Frame extraction failed: {e.stderr}")

    def assemble_video(
        self,
        frames_dir: Path,
        output_path: Path,
        fps: float,
        pattern: str = "frame_%06d.png",
        encoder: str = "h264_nvenc",
        pix_fmt: str = "yuv420p"
    ) -> Path:
        """
        Assemble video from frames.

        Args:
            frames_dir: Directory containing frames
            output_path: Output video path
            fps: Frames per second
            pattern: Frame filename pattern
            encoder: Video encoder to use
            pix_fmt: Pixel format

        Returns:
            Path to assembled video

        Raises:
            AssemblyError: If assembly fails
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        input_pattern = frames_dir / pattern

        # Build ffmpeg command
        cmd = [
            'ffmpeg',
            '-y',
            '-framerate', str(fps),
            '-i', str(input_pattern),
            '-c:v', encoder,
            '-pix_fmt', pix_fmt,
        ]

        # Add encoder-specific options
        if encoder == "h264_nvenc":
            cmd.extend(['-preset', 'p6', '-cq', '19'])
        elif encoder == "libx264":
            cmd.extend(['-crf', '18', '-preset', 'medium'])

        cmd.append(str(output_path))

        self._logger.info(f"Assembling video with encoder: {encoder}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=3600  # 1 hour timeout
            )

            if not output_path.exists() or output_path.stat().st_size == 0:
                raise AssemblyError("Output video is empty or missing")

            self._logger.info(f"Assembled video: {output_path}")
            return output_path

        except subprocess.CalledProcessError as e:
            # If nvenc fails, this will be caught by caller for fallback
            raise AssemblyError(f"Video assembly failed: {e.stderr}")

    def test_encoder(self, encoder: str) -> bool:
        """Test if encoder is available."""
        cmd = [
            'ffmpeg',
            '-hide_banner',
            '-encoders'
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return encoder in result.stdout
        except:
            return False

