#!/usr/bin/env python3
"""
Simple script to generate test images for subtitle and watermark removal.
Run with: python generate_test_images.py
"""

import numpy as np
import cv2
from pathlib import Path


def create_subtitle_frame(width=1280, height=720, text="TEST SUBTITLE"):
    """Create frame with subtitle at bottom."""
    # Gradient background
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        color_value = int(255 * (1 - y / height))
        frame[y, :] = [color_value, color_value // 2, 0]

    # Add content circles
    cv2.circle(frame, (width // 4, height // 3), 50, (0, 255, 0), -1)
    cv2.circle(frame, (3 * width // 4, height // 3), 40, (255, 0, 0), -1)

    # Add subtitle at bottom
    subtitle_y = int(height * 0.85)
    cv2.rectangle(frame, (0, subtitle_y), (width, height), (0, 0, 0), -1)

    # White text with black outline
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(text, font, 1.0, 2)[0]
    text_x = (width - text_size[0]) // 2
    text_y = subtitle_y + 30

    cv2.putText(frame, text, (text_x, text_y), font, 1.0, (0, 0, 0), 4)
    cv2.putText(frame, text, (text_x, text_y), font, 1.0, (255, 255, 255), 2)

    return frame


def create_watermark_frame(width=1280, height=720, position='top-right', text='©LOGO'):
    """Create frame with watermark."""
    # Gradient background
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        color_value = int(255 * (1 - y / height))
        frame[y, :] = [0, color_value // 2, color_value]

    # Add content
    cv2.circle(frame, (width // 2, height // 2), 60, (0, 255, 255), -1)

    # Add watermark
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(text, font, 0.7, 2)[0]
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

    # Semi-transparent watermark
    overlay = frame.copy()
    cv2.putText(overlay, text, (text_x, text_y), font, 0.7, (255, 255, 255), 2)
    frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)

    return frame


def main():
    """Generate all test images."""
    output_dir = Path("output/test_images")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Generating test images...")

    # Subtitle test images
    subtitle_dir = output_dir / "subtitles"
    subtitle_dir.mkdir(exist_ok=True)

    subtitles = [
        "Hello, how are you?",
        "This is a test subtitle",
        "Example subtitle text",
        "♪ Music playing ♪",
        "12:34:56 - Timestamp"
    ]

    for i, text in enumerate(subtitles):
        frame = create_subtitle_frame(1280, 720, text)
        output_path = subtitle_dir / f"subtitle_{i:02d}.jpg"
        cv2.imwrite(str(output_path), frame)
        print(f"✓ Created {output_path}")

    # Watermark test images
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
        frame = create_watermark_frame(1280, 720, pos, text)
        output_path = watermark_dir / f"watermark_{pos}.jpg"
        cv2.imwrite(str(output_path), frame)
        print(f"✓ Created {output_path}")

    # Multi-watermark frame
    multi_frame = create_watermark_frame(1280, 720, 'top-right', '©LOGO')
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(multi_frame, "@TV", (20, 700), font, 0.7, (255, 255, 255), 2)
    output_path = watermark_dir / "multi_watermark.jpg"
    cv2.imwrite(str(output_path), multi_frame)
    print(f"✓ Created {output_path}")

    print(f"\n✅ All test images created successfully!")
    print(f"📁 Location: {output_dir.absolute()}")
    print(f"   - Subtitles: {len(subtitles)} images")
    print(f"   - Watermarks: {len(watermark_configs) + 1} images")


if __name__ == '__main__':
    main()

