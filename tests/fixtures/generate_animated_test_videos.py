"""
Synthetic Test Video Generator for v2.1 Animated Text Detection.
Creates 4 specific scenarios to test optical flow tracking:
1. Ticker Tape (Linear Pan) - TikTok style moving text
2. Karaoke (Color Change) - HSV color progression
3. Shake (Camera Shake) - Global motion vs text motion
4. Fade (Alpha Fade) - Text disappearing

Version: 2.1.0
Date: January 3, 2026
"""

import numpy as np
import cv2
from pathlib import Path
import subprocess
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)


class SyntheticVideoGenerator:
    """
    Generates synthetic test videos for optical flow validation.

    Each scenario tests specific aspects of animated text detection:
    - Ticker Tape: Tests bbox tracking accuracy
    - Karaoke: Tests HSV color change detection
    - Shake: Tests global vs local motion discrimination
    - Fade: Tests when tracker should "release" mask
    """

    def __init__(self, fps: int = 24, resolution: Tuple[int, int] = (640, 480)):
        """
        Initialize generator.

        Args:
            fps: Frames per second (default: 24)
            resolution: (width, height) tuple (default: 640x480)
        """
        self.fps = fps
        self.width, self.height = resolution

        logger.info(f"SyntheticVideoGenerator initialized ({self.width}x{self.height} @ {fps}fps)")

    def create_ticker_tape_video(self,
                                 output_path: Path,
                                 duration: float = 5.0,
                                 text: str = "BREAKING NEWS") -> bool:
        """
        Scenario 1: Ticker Tape (Бегущая строка)

        White text on black background, moving left to right.
        Tests optical flow tracking accuracy.

        Args:
            output_path: Path to save video
            duration: Duration in seconds
            text: Text to display

        Returns:
            True if successful
        """
        logger.info(f"Generating Ticker Tape video: {output_path}")

        total_frames = int(duration * self.fps)
        frames = []

        # Text parameters
        font = cv2.FONT_HERSHEY_BOLD
        font_scale = 1.5
        thickness = 3
        text_color = (255, 255, 255)  # White

        # Movement parameters
        start_x = -200  # Start off-screen left
        end_x = self.width + 200  # End off-screen right
        y_position = self.height // 2

        for i in range(total_frames):
            # Create black frame
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

            # Calculate current text position (linear interpolation)
            progress = i / total_frames
            current_x = int(start_x + (end_x - start_x) * progress)

            # Draw text
            cv2.putText(
                frame, text,
                (current_x, y_position),
                font, font_scale, text_color, thickness
            )

            # Add frame number indicator (top-left)
            cv2.putText(
                frame, f"Frame {i}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1
            )

            frames.append(frame)

        # Save video with audio
        return self._save_video_with_audio(frames, output_path)

    def create_karaoke_video(self,
                            output_path: Path,
                            duration: float = 5.0,
                            text: str = "KARAOKE TEXT") -> bool:
        """
        Scenario 2: Karaoke (Смена цвета)

        Static text that changes color: white → yellow → red
        Tests HSV color change detection.

        Args:
            output_path: Path to save video
            duration: Duration in seconds
            text: Text to display

        Returns:
            True if successful
        """
        logger.info(f"Generating Karaoke video: {output_path}")

        total_frames = int(duration * self.fps)
        frames = []

        # Text parameters
        font = cv2.FONT_HERSHEY_BOLD
        font_scale = 2.0
        thickness = 4
        x_position = self.width // 2 - 200
        y_position = self.height // 2

        # Color progression (BGR format)
        colors = [
            (255, 255, 255),  # White (start)
            (0, 255, 255),    # Yellow (middle)
            (0, 0, 255)       # Red (end)
        ]

        for i in range(total_frames):
            # Create black frame
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

            # Calculate current color (smooth interpolation)
            progress = i / total_frames

            if progress < 0.5:
                # White → Yellow (first half)
                t = progress * 2  # Normalize to 0-1
                color = self._interpolate_color(colors[0], colors[1], t)
            else:
                # Yellow → Red (second half)
                t = (progress - 0.5) * 2
                color = self._interpolate_color(colors[1], colors[2], t)

            # Draw text with current color
            cv2.putText(
                frame, text,
                (x_position, y_position),
                font, font_scale, color, thickness
            )

            # Add color indicator (top-left)
            cv2.putText(
                frame, f"Frame {i}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1
            )

            # Add color bar indicator (top-right)
            cv2.rectangle(frame, (self.width - 100, 10), (self.width - 10, 40), color, -1)

            frames.append(frame)

        return self._save_video_with_audio(frames, output_path)

    def create_shake_video(self,
                          output_path: Path,
                          duration: float = 5.0,
                          text: str = "STABLE TEXT") -> bool:
        """
        Scenario 3: Shake (Дрожание камеры)

        Text is stable relative to background, but entire frame shakes.
        Tests global vs local motion discrimination.

        Args:
            output_path: Path to save video
            duration: Duration in seconds
            text: Text to display

        Returns:
            True if successful
        """
        logger.info(f"Generating Shake video: {output_path}")

        total_frames = int(duration * self.fps)
        frames = []

        # Text parameters
        font = cv2.FONT_HERSHEY_BOLD
        font_scale = 1.8
        thickness = 3
        text_color = (255, 255, 255)

        # Create base frame with text and background pattern
        base_frame = np.zeros((self.height + 100, self.width + 100, 3), dtype=np.uint8)

        # Add grid background (so shake is visible)
        for y in range(0, self.height + 100, 50):
            cv2.line(base_frame, (0, y), (self.width + 100, y), (50, 50, 50), 1)
        for x in range(0, self.width + 100, 50):
            cv2.line(base_frame, (x, 0), (x, self.height + 100), (50, 50, 50), 1)

        # Draw text on base frame
        text_x = (self.width + 100) // 2 - 150
        text_y = (self.height + 100) // 2
        cv2.putText(base_frame, text, (text_x, text_y), font, font_scale, text_color, thickness)

        # Generate shake motion
        shake_amplitude = 10  # pixels

        for i in range(total_frames):
            # Calculate shake offset (sine wave for smooth shake)
            t = i / self.fps
            offset_x = int(shake_amplitude * np.sin(t * 2 * np.pi * 2))  # 2 Hz
            offset_y = int(shake_amplitude * np.cos(t * 2 * np.pi * 3))  # 3 Hz (different freq)

            # Crop shaken frame from base
            crop_x = 50 + offset_x
            crop_y = 50 + offset_y
            frame = base_frame[crop_y:crop_y+self.height, crop_x:crop_x+self.width].copy()

            # Add frame indicator
            cv2.putText(frame, f"Frame {i}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1)

            frames.append(frame)

        return self._save_video_with_audio(frames, output_path)

    def create_fade_video(self,
                         output_path: Path,
                         duration: float = 5.0,
                         text: str = "FADING TEXT") -> bool:
        """
        Scenario 4: Fade (Исчезновение)

        Text fades from opaque to transparent (alpha blend).
        Tests when tracker should "release" mask.

        Args:
            output_path: Path to save video
            duration: Duration in seconds
            text: Text to display

        Returns:
            True if successful
        """
        logger.info(f"Generating Fade video: {output_path}")

        total_frames = int(duration * self.fps)
        frames = []

        # Text parameters
        font = cv2.FONT_HERSHEY_BOLD
        font_scale = 2.0
        thickness = 4
        text_color = (255, 255, 255)
        x_position = self.width // 2 - 200
        y_position = self.height // 2

        for i in range(total_frames):
            # Create black frame
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

            # Calculate alpha (fade out in second half)
            progress = i / total_frames
            if progress < 0.5:
                alpha = 1.0  # First half: fully opaque
            else:
                alpha = 1.0 - 2 * (progress - 0.5)  # Second half: fade to 0

            # Create text overlay with alpha
            overlay = frame.copy()
            cv2.putText(overlay, text, (x_position, y_position),
                       font, font_scale, text_color, thickness)

            # Blend overlay with base frame
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

            # Add frame indicator and alpha value
            cv2.putText(frame, f"Frame {i} | Alpha {alpha:.2f}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1)

            frames.append(frame)

        return self._save_video_with_audio(frames, output_path)

    def create_static_control_video(self,
                                   output_path: Path,
                                   duration: float = 3.0,
                                   text: str = "STATIC TEXT") -> bool:
        """
        Control scenario: Static text (no motion, no color change).
        Tests baseline v2.0 compatibility.

        Args:
            output_path: Path to save video
            duration: Duration in seconds
            text: Text to display

        Returns:
            True if successful
        """
        logger.info(f"Generating Static Control video: {output_path}")

        total_frames = int(duration * self.fps)
        frames = []

        # Text parameters
        font = cv2.FONT_HERSHEY_BOLD
        font_scale = 1.8
        thickness = 3
        text_color = (255, 255, 255)
        x_position = self.width // 2 - 150
        y_position = self.height // 2

        for i in range(total_frames):
            # Create black frame
            frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)

            # Draw static text
            cv2.putText(frame, text, (x_position, y_position),
                       font, font_scale, text_color, thickness)

            # Add frame indicator
            cv2.putText(frame, f"Frame {i}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 1)

            frames.append(frame)

        return self._save_video_with_audio(frames, output_path)

    def _interpolate_color(self, color1: Tuple[int, int, int],
                          color2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
        """
        Interpolate between two BGR colors.

        Args:
            color1: Start color (B, G, R)
            color2: End color (B, G, R)
            t: Interpolation factor (0.0 to 1.0)

        Returns:
            Interpolated color
        """
        b = int(color1[0] * (1 - t) + color2[0] * t)
        g = int(color1[1] * (1 - t) + color2[1] * t)
        r = int(color1[2] * (1 - t) + color2[2] * t)
        return (b, g, r)

    def _save_video_with_audio(self, frames: List[np.ndarray], output_path: Path) -> bool:
        """
        Save frames as video with audio track (440Hz sine wave).

        Args:
            frames: List of BGR frames
            output_path: Output path

        Returns:
            True if successful
        """
        if not frames:
            logger.error("No frames to save")
            return False

        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Save frames as temporary video (no audio)
        temp_video = output_path.parent / f"temp_{output_path.name}"

        h, w = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(temp_video), fourcc, self.fps, (w, h))

        for frame in frames:
            out.write(frame)

        out.release()

        # Add audio using FFmpeg
        duration = len(frames) / self.fps

        cmd = [
            'ffmpeg', '-y',
            '-i', str(temp_video),
            '-f', 'lavfi',
            '-i', f'sine=frequency=440:duration={duration}',
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-shortest',
            str(output_path)
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"FFmpeg error: {result.stderr}")
                # Fallback: save without audio
                temp_video.rename(output_path)
                logger.warning(f"Saved video without audio: {output_path}")
                return True

            # Cleanup temp file
            temp_video.unlink()

            logger.info(f"✅ Video saved with audio: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to add audio: {e}")
            # Fallback: save without audio
            if temp_video.exists():
                temp_video.rename(output_path)
            return True


def generate_all_test_videos(output_dir: Path = None):
    """
    Generate all 4 test scenarios + control.

    Args:
        output_dir: Output directory (default: tests/fixtures/videos/animated)
    """
    if output_dir is None:
        output_dir = Path("tests/fixtures/videos/animated")

    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO)
    logger.info("Generating synthetic test videos for v2.1...")

    generator = SyntheticVideoGenerator(fps=24, resolution=(640, 480))

    # 1. Ticker Tape (Linear Pan)
    logger.info("\n=== Scenario 1: Ticker Tape ===")
    generator.create_ticker_tape_video(
        output_dir / "01_ticker_tape.mp4",
        duration=5.0,
        text="BREAKING NEWS"
    )

    # 2. Karaoke (Color Change)
    logger.info("\n=== Scenario 2: Karaoke ===")
    generator.create_karaoke_video(
        output_dir / "02_karaoke.mp4",
        duration=5.0,
        text="KARAOKE TEXT"
    )

    # 3. Shake (Camera Shake)
    logger.info("\n=== Scenario 3: Shake ===")
    generator.create_shake_video(
        output_dir / "03_shake.mp4",
        duration=5.0,
        text="STABLE TEXT"
    )

    # 4. Fade (Alpha Fade)
    logger.info("\n=== Scenario 4: Fade ===")
    generator.create_fade_video(
        output_dir / "04_fade.mp4",
        duration=5.0,
        text="FADING TEXT"
    )

    # 5. Static Control
    logger.info("\n=== Scenario 5: Static Control ===")
    generator.create_static_control_video(
        output_dir / "05_static_control.mp4",
        duration=3.0,
        text="STATIC TEXT"
    )

    logger.info(f"\n✅ All test videos generated in: {output_dir.absolute()}")
    logger.info("\nTest Matrix:")
    logger.info("| Video                | Motion | Color | Expected Classification |")
    logger.info("|----------------------|--------|-------|-------------------------|")
    logger.info("| 01_ticker_tape.mp4   | ✅ Yes | ❌ No  | 'moving'                |")
    logger.info("| 02_karaoke.mp4       | ❌ No  | ✅ Yes | 'karaoke'               |")
    logger.info("| 03_shake.mp4         | ✅ Yes | ❌ No  | 'static' (global motion)|")
    logger.info("| 04_fade.mp4          | ❌ No  | ❌ No  | 'static' → none         |")
    logger.info("| 05_static_control.mp4| ❌ No  | ❌ No  | 'static'                |")


if __name__ == '__main__':
    generate_all_test_videos()

