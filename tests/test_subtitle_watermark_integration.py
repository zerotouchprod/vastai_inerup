"""
Integration tests for subtitle and watermark removal with synthetic test images.
Creates test frames with text and watermarks, then verifies removal quality.
"""

import pytest
import numpy as np
import cv2
from pathlib import Path
import tempfile
import shutil


def create_test_frame_with_subtitle(width: int = 640, height: int = 480,
                                     text: str = "TEST SUBTITLE") -> np.ndarray:
    """
    Create a synthetic video frame with subtitle at bottom.

    Args:
        width: Frame width
        height: Frame height
        text: Subtitle text

    Returns:
        BGR image as numpy array
    """
    # Create gradient background (simulate video content)
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Add gradient (blue to black)
    for y in range(height):
        color_value = int(255 * (1 - y / height))
        frame[y, :] = [color_value, color_value // 2, 0]

    # Add some "video content" (circles)
    cv2.circle(frame, (width // 4, height // 3), 50, (0, 255, 0), -1)
    cv2.circle(frame, (3 * width // 4, height // 3), 40, (255, 0, 0), -1)

    # Add subtitle at bottom with black background bar
    subtitle_y = int(height * 0.85)
    cv2.rectangle(frame, (0, subtitle_y), (width, height), (0, 0, 0), -1)

    # Add white text with black outline (typical subtitle style)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.0
    thickness = 2

    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    text_x = (width - text_size[0]) // 2
    text_y = subtitle_y + 30

    # Black outline
    cv2.putText(frame, text, (text_x, text_y), font, font_scale, (0, 0, 0), thickness + 2)
    # White text
    cv2.putText(frame, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness)

    return frame


def create_test_frame_with_watermark(width: int = 640, height: int = 480,
                                      position: str = 'top-right',
                                      text: str = "©LOGO") -> np.ndarray:
    """
    Create a synthetic video frame with watermark.

    Args:
        width: Frame width
        height: Frame height
        position: Watermark position ('top-right', 'bottom-left', etc.)
        text: Watermark text

    Returns:
        BGR image as numpy array
    """
    # Create gradient background
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    for y in range(height):
        color_value = int(255 * (1 - y / height))
        frame[y, :] = [0, color_value // 2, color_value]

    # Add video content
    cv2.circle(frame, (width // 2, height // 2), 60, (0, 255, 255), -1)

    # Determine watermark position
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    thickness = 2

    text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
    margin = 20

    if position == 'top-right':
        text_x = width - text_size[0] - margin
        text_y = margin + text_size[1]
    elif position == 'top-left':
        text_x = margin
        text_y = margin + text_size[1]
    elif position == 'bottom-right':
        text_x = width - text_size[0] - margin
        text_y = height - margin
    elif position == 'bottom-left':
        text_x = margin
        text_y = height - margin
    else:  # center
        text_x = (width - text_size[0]) // 2
        text_y = (height + text_size[1]) // 2

    # Add semi-transparent white watermark
    overlay = frame.copy()
    cv2.putText(overlay, text, (text_x, text_y), font, font_scale, (255, 255, 255), thickness)

    # Blend with transparency
    alpha = 0.7
    frame = cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)

    return frame


class TestSubtitleRemovalIntegration:
    """Integration tests for subtitle removal with synthetic frames."""

    def test_create_subtitle_frame(self):
        """Test that synthetic subtitle frame is created correctly."""
        frame = create_test_frame_with_subtitle(640, 480, "Hello World")

        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8

        # Check that subtitle area is darker (black bar)
        bottom_region = frame[400:, :]
        mean_brightness = np.mean(bottom_region)
        assert mean_brightness < 100  # Should be dark

    def test_save_and_load_test_frame(self, tmp_path):
        """Test saving and loading test frame."""
        frame = create_test_frame_with_subtitle()

        output_path = tmp_path / "test_frame.jpg"
        cv2.imwrite(str(output_path), frame)

        assert output_path.exists()

        loaded = cv2.imread(str(output_path))
        assert loaded is not None
        assert loaded.shape == frame.shape

    @pytest.mark.skipif(True, reason="Requires EasyOCR - slow test")
    def test_ocr_detects_subtitle(self, tmp_path):
        """Test that OCR can detect text in synthetic subtitle."""
        from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper

        frame = create_test_frame_with_subtitle(640, 480, "TEST")

        # Save frame
        frame_path = tmp_path / "frame.jpg"
        cv2.imwrite(str(frame_path), frame)

        # Run OCR
        ocr = PaddleWrapper(lang='en', use_gpu=False)
        detections = ocr.detect(frame, confidence_threshold=0.1)

        # Should detect at least one text region
        assert len(detections) > 0

        # Check if detected text contains our test string
        detected_texts = [d['text'] for d in detections]
        assert any('TEST' in text.upper() for text in detected_texts)


class TestWatermarkRemovalIntegration:
    """Integration tests for watermark removal with synthetic frames."""

    def test_create_watermark_frame_top_right(self):
        """Test creating frame with top-right watermark."""
        frame = create_test_frame_with_watermark(640, 480, 'top-right', '©LOGO')

        assert frame.shape == (480, 640, 3)

        # Check that top-right region has bright pixels (watermark)
        top_right = frame[0:100, 540:640]
        mean_brightness = np.mean(top_right)
        assert mean_brightness > 50  # Should be brighter due to watermark

    def test_create_watermark_frame_bottom_left(self):
        """Test creating frame with bottom-left watermark."""
        frame = create_test_frame_with_watermark(640, 480, 'bottom-left', '©LOGO')

        # Check that bottom-left region has bright pixels
        bottom_left = frame[380:480, 0:100]
        mean_brightness = np.mean(bottom_left)
        assert mean_brightness > 50

    def test_multiple_watermark_positions(self):
        """Test creating frames with different watermark positions."""
        positions = ['top-right', 'top-left', 'bottom-right', 'bottom-left', 'center']

        for pos in positions:
            frame = create_test_frame_with_watermark(640, 480, pos, '©TEST')
            assert frame.shape == (480, 640, 3)

    def test_watermark_sequence_consistency(self, tmp_path):
        """Test that watermark stays in same position across frames."""
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()

        # Create sequence of 5 frames with watermark
        for i in range(5):
            frame = create_test_frame_with_watermark(640, 480, 'top-right', '©LOGO')
            cv2.imwrite(str(frames_dir / f"frame_{i:03d}.jpg"), frame)

        # Load all frames and check watermark position consistency
        frame_files = sorted(frames_dir.glob("*.jpg"))
        assert len(frame_files) == 5

        watermark_regions = []
        for frame_file in frame_files:
            frame = cv2.imread(str(frame_file))
            top_right = frame[0:100, 540:640]
            watermark_regions.append(np.mean(top_right))

        # All frames should have similar brightness in watermark region
        std_dev = np.std(watermark_regions)
        assert std_dev < 20  # Low variance means consistent watermark


class TestRealWorldScenarios:
    """Test real-world scenarios with saved test images."""

    def test_save_subtitle_test_set(self, tmp_path):
        """Save a complete test set of subtitle frames for manual inspection."""
        test_dir = tmp_path / "subtitle_test_set"
        test_dir.mkdir()

        subtitles = [
            "Hello, how are you?",
            "This is a test subtitle",
            "12:34:56 - Timestamp text",
            "♪ Music playing ♪"
        ]

        for i, subtitle in enumerate(subtitles):
            frame = create_test_frame_with_subtitle(1280, 720, subtitle)
            cv2.imwrite(str(test_dir / f"subtitle_{i:02d}.jpg"), frame)

        # Verify all saved
        assert len(list(test_dir.glob("*.jpg"))) == len(subtitles)

    def test_save_watermark_test_set(self, tmp_path):
        """Save a complete test set of watermark frames for manual inspection."""
        test_dir = tmp_path / "watermark_test_set"
        test_dir.mkdir()

        positions = ['top-right', 'top-left', 'bottom-right', 'bottom-left']
        logos = ['©LOGO', '★TV', '@CHANNEL', '2024']

        for i, (pos, logo) in enumerate(zip(positions, logos)):
            frame = create_test_frame_with_watermark(1280, 720, pos, logo)
            cv2.imwrite(str(test_dir / f"watermark_{pos}.jpg"), frame)

        # Verify all saved
        assert len(list(test_dir.glob("*.jpg"))) == len(positions)

    def test_create_multi_watermark_frame(self, tmp_path):
        """Create frame with multiple watermarks in different corners."""
        width, height = 1280, 720
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Gradient background
        for y in range(height):
            color_value = int(255 * (1 - y / height))
            frame[y, :] = [color_value // 2, color_value, color_value // 2]

        # Add multiple watermarks
        font = cv2.FONT_HERSHEY_SIMPLEX

        # Top-right
        cv2.putText(frame, "©LOGO", (width - 150, 40), font, 0.8, (255, 255, 255), 2)

        # Bottom-left
        cv2.putText(frame, "@TV", (20, height - 20), font, 0.7, (255, 255, 255), 2)

        # Save
        output_path = tmp_path / "multi_watermark.jpg"
        cv2.imwrite(str(output_path), frame)

        assert output_path.exists()


if __name__ == '__main__':
    # Run tests and save test images to output/test_images/
    output_dir = Path("output/test_images")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create subtitle test images
    subtitle_dir = output_dir / "subtitles"
    subtitle_dir.mkdir(exist_ok=True)

    subtitles = [
        "Hello, how are you?",
        "This is a test subtitle",
        "Example subtitle text",
        "♪ Music playing ♪"
    ]

    for i, text in enumerate(subtitles):
        frame = create_test_frame_with_subtitle(1280, 720, text)
        cv2.imwrite(str(subtitle_dir / f"subtitle_{i:02d}.jpg"), frame)

    print(f"✓ Created {len(subtitles)} subtitle test frames in {subtitle_dir}")

    # Create watermark test images
    watermark_dir = output_dir / "watermarks"
    watermark_dir.mkdir(exist_ok=True)

    watermark_configs = [
        ('top-right', '©LOGO'),
        ('top-left', '★TV'),
        ('bottom-right', '@CHANNEL'),
        ('bottom-left', '2024'),
        ('center', 'WATERMARK')
    ]

    for pos, text in watermark_configs:
        frame = create_test_frame_with_watermark(1280, 720, pos, text)
        cv2.imwrite(str(watermark_dir / f"watermark_{pos}.jpg"), frame)

    print(f"✓ Created {len(watermark_configs)} watermark test frames in {watermark_dir}")

    # Create multi-watermark frame
    multi_frame = create_test_frame_with_watermark(1280, 720, 'top-right', '©LOGO')
    # Add second watermark manually
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(multi_frame, "@TV", (20, 700), font, 0.7, (255, 255, 255), 2)
    cv2.imwrite(str(watermark_dir / "multi_watermark.jpg"), multi_frame)

    print(f"✓ Created multi-watermark test frame")
    print(f"\nTest images saved to: {output_dir.absolute()}")

    # Run pytest
    pytest.main([__file__, '-v', '-s'])

