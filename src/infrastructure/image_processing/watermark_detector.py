"""
Static watermark detection module.
Detects persistent regions that appear across multiple frames (logos, channel watermarks).
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def detect_static_regions(frames: List[np.ndarray],
                          persistence_threshold: float = 0.8,
                          sample_ratio: float = 0.3) -> np.ndarray:
    """
    Find regions that appear consistently across frames (static watermarks).

    Args:
        frames: List of BGR frames (numpy arrays)
        persistence_threshold: Ratio of frames a pixel must appear in to be considered static (0.0-1.0)
        sample_ratio: Ratio of frames to sample for detection (0.0-1.0) to speed up processing

    Returns:
        Binary mask of persistent regions (uint8, 0-255)

    Example:
        If persistence_threshold=0.8 and we have 100 frames, a pixel must appear
        in at least 80 frames to be marked as static watermark.
    """
    if not frames:
        logger.warning("detect_static_regions: No frames provided")
        return np.zeros((100, 100), dtype=np.uint8)

    # Sample frames to speed up detection
    total_frames = len(frames)
    sample_count = max(3, int(total_frames * sample_ratio))
    sample_step = max(1, total_frames // sample_count)
    sampled_frames = frames[::sample_step][:sample_count]

    logger.info(f"Detecting static regions using {len(sampled_frames)}/{total_frames} frames")

    # Initialize accumulator
    h, w = sampled_frames[0].shape[:2]
    accumulator = np.zeros((h, w), dtype=np.float32)

    # Accumulate edge detections across frames
    for i, frame in enumerate(sampled_frames):
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect edges (watermarks have sharp edges)
        edges = cv2.Canny(gray, 100, 200)

        # Add to accumulator (normalized)
        accumulator += (edges > 0).astype(np.float32)

    # Normalize accumulator to [0, 1]
    accumulator /= len(sampled_frames)

    # Threshold by persistence
    static_mask = (accumulator >= persistence_threshold).astype(np.uint8) * 255

    # Clean up mask (remove noise, fill holes)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    static_mask = cv2.morphologyEx(static_mask, cv2.MORPH_CLOSE, kernel)
    static_mask = cv2.morphologyEx(static_mask, cv2.MORPH_OPEN, kernel)

    # Log statistics
    coverage = np.sum(static_mask > 0) / (h * w)
    logger.info(f"Static region detection: {coverage*100:.2f}% of frame marked as persistent")

    return static_mask


def create_persistent_mask(frame_paths: List[Path],
                           roi_list: List[Tuple[int, int, int, int]],
                           persistence_threshold: float = 0.8) -> np.ndarray:
    """
    Generate unified mask for static watermarks in specified ROI zones.

    Args:
        frame_paths: List of paths to frame images
        roi_list: List of (x, y, w, h) tuples defining ROI zones to check
        persistence_threshold: Ratio of frames a pixel must appear in

    Returns:
        Binary mask of persistent watermarks (uint8, 0-255)
    """
    if not frame_paths:
        logger.warning("create_persistent_mask: No frame paths provided")
        return np.zeros((100, 100), dtype=np.uint8)

    # Load first frame to get dimensions
    first_frame = cv2.imread(str(frame_paths[0]))
    if first_frame is None:
        logger.error(f"Failed to read first frame: {frame_paths[0]}")
        return np.zeros((100, 100), dtype=np.uint8)

    h, w = first_frame.shape[:2]
    final_mask = np.zeros((h, w), dtype=np.uint8)

    # Sample frames (every 10th frame or max 50 frames)
    sample_step = max(1, len(frame_paths) // 50)
    sampled_paths = frame_paths[::sample_step][:50]

    logger.info(f"Creating persistent mask from {len(sampled_paths)}/{len(frame_paths)} frames for {len(roi_list)} ROI(s)")

    # Load sampled frames
    frames = []
    for path in sampled_paths:
        frame = cv2.imread(str(path))
        if frame is not None:
            frames.append(frame)

    if not frames:
        logger.error("Failed to load any frames")
        return final_mask

    # Detect static regions in each ROI
    for roi_idx, (x, y, roi_w, roi_h) in enumerate(roi_list):
        logger.debug(f"Processing ROI {roi_idx+1}/{len(roi_list)}: ({x},{y},{roi_w},{roi_h})")

        # Extract ROI from all frames
        roi_frames = []
        for frame in frames:
            roi_crop = frame[y:y+roi_h, x:x+roi_w]
            roi_frames.append(roi_crop)

        # Detect static regions in this ROI
        roi_mask = detect_static_regions(roi_frames, persistence_threshold)

        # Place ROI mask back into full frame coordinates
        final_mask[y:y+roi_h, x:x+roi_w] = cv2.bitwise_or(
            final_mask[y:y+roi_h, x:x+roi_w],
            roi_mask
        )

    # Final cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, kernel)

    total_coverage = np.sum(final_mask > 0) / (h * w)
    logger.info(f"Persistent mask created: {total_coverage*100:.2f}% of frame")

    return final_mask


def expand_watermark_mask(mask: np.ndarray, expansion: int = 10) -> np.ndarray:
    """
    Expand watermark mask to cover semi-transparent edges and shadows.

    Args:
        mask: Input binary mask
        expansion: Expansion radius in pixels

    Returns:
        Expanded binary mask
    """
    if expansion <= 0:
        return mask

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (expansion*2+1, expansion*2+1))
    expanded = cv2.dilate(mask, kernel, iterations=1)

    # Smooth edges
    expanded = cv2.GaussianBlur(expanded, (5, 5), 0)
    _, expanded = cv2.threshold(expanded, 127, 255, cv2.THRESH_BINARY)

    return expanded


def validate_watermark_regions(mask: np.ndarray,
                               min_area: int = 100,
                               max_area_ratio: float = 0.05) -> np.ndarray:
    """
    Filter watermark mask to keep only reasonably-sized regions.

    Args:
        mask: Input binary mask
        min_area: Minimum region area in pixels
        max_area_ratio: Maximum region area as ratio of total frame area

    Returns:
        Filtered binary mask
    """
    h, w = mask.shape
    total_area = h * w
    max_area = int(total_area * max_area_ratio)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter by area
    filtered = np.zeros_like(mask)
    kept_count = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area <= area <= max_area:
            cv2.drawContours(filtered, [cnt], -1, 255, -1)
            kept_count += 1

    logger.debug(f"Watermark validation: kept {kept_count}/{len(contours)} regions")

    return filtered

