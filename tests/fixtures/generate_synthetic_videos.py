"""
Generate synthetic test videos with audio for testing.
Creates videos with known properties for automated testing.
"""

import numpy as np
import cv2
from pathlib import Path
import subprocess
import logging

logger = logging.getLogger(__name__)


def generate_test_video_with_audio(
    output_path: Path,
    duration: float = 5.0,
    fps: int = 24,
    width: int = 640,
    height: int = 480,
    with_subtitle: bool = False,
    subtitle_text: str = "TEST SUBTITLE"
) -> bool:
    """
    Generate synthetic video with audio track.

    Args:
        output_path: Path to save video
        duration: Video duration in seconds
        fps: Frames per second
        width: Video width
        height: Video height
        with_subtitle: Add subtitle to bottom
        subtitle_text: Subtitle text

    Returns:
        True if successful
    """
    try:
        # Create temporary video without audio
        temp_video = output_path.parent / f"temp_{output_path.name}"

        # Generate frames
        total_frames = int(duration * fps)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(temp_video), fourcc, fps, (width, height))

        logger.info(f"Generating {total_frames} frames ({width}x{height} @ {fps}fps)")

        for i in range(total_frames):
            # Create frame with gradient and animation
            frame = np.zeros((height, width, 3), dtype=np.uint8)

            # Animated gradient background
            phase = i / total_frames
            for y in range(height):
                color_value = int(128 + 127 * np.sin(y / height * np.pi * 2 + phase * np.pi * 2))
                frame[y, :] = [color_value // 2, color_value, color_value // 3]

            # Add moving circle (animation content)
            circle_x = int(width * phase)
            circle_y = height // 2
            cv2.circle(frame, (circle_x, circle_y), 40, (255, 255, 0), -1)

            # Add frame counter
            cv2.putText(frame, f"Frame {i}", (20, 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            # Add subtitle if requested
            if with_subtitle:
                subtitle_y = int(height * 0.85)
                cv2.rectangle(frame, (0, subtitle_y), (width, height), (0, 0, 0), -1)

                text_size = cv2.getTextSize(subtitle_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]
                text_x = (width - text_size[0]) // 2
                text_y = subtitle_y + 30

                cv2.putText(frame, subtitle_text, (text_x, text_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
                cv2.putText(frame, subtitle_text, (text_x, text_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

            out.write(frame)

        out.release()
        logger.info(f"Video frames generated: {temp_video}")

        # Add audio using FFmpeg
        # Generate 440Hz sine wave (A note)
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

        logger.info("Adding audio track...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False

        # Cleanup temp file
        temp_video.unlink()

        logger.info(f"✅ Test video created: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate test video: {e}")
        return False


def generate_silent_video(
    output_path: Path,
    duration: float = 3.0,
    fps: int = 24,
    width: int = 640,
    height: int = 480
) -> bool:
    """Generate video without audio track."""
    try:
        total_frames = int(duration * fps)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

        for i in range(total_frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)

            # Simple gradient
            for y in range(height):
                color = int(255 * y / height)
                frame[y, :] = [color, color // 2, 0]

            # Frame number
            cv2.putText(frame, f"Frame {i}", (20, 40),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            out.write(frame)

        out.release()
        logger.info(f"✅ Silent video created: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to generate silent video: {e}")
        return False


def main():
    """Generate all test videos."""
    output_dir = Path("tests/fixtures/videos")
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO)

    print("Generating synthetic test videos...")

    # 1. Video with audio
    print("\n1. Generating video with audio...")
    generate_test_video_with_audio(
        output_dir / "sample_with_audio.mp4",
        duration=5.0
    )

    # 2. Silent video
    print("\n2. Generating silent video...")
    generate_silent_video(
        output_dir / "sample_silent.mp4",
        duration=3.0
    )

    # 3. Video with subtitles
    print("\n3. Generating video with subtitles...")
    generate_test_video_with_audio(
        output_dir / "sample_subtitles.mp4",
        duration=5.0,
        with_subtitle=True,
        subtitle_text="TEST SUBTITLE"
    )

    # 4. Short video for quick tests
    print("\n4. Generating short test video...")
    generate_test_video_with_audio(
        output_dir / "sample_short.mp4",
        duration=2.0,
        fps=24,
        width=320,
        height=240
    )

    print("\n✅ All test videos generated successfully!")
    print(f"Location: {output_dir.absolute()}")


if __name__ == '__main__':
    main()

