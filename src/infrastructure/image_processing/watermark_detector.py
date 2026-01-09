"""
Static watermark detection module.
Detects persistent regions that appear across multiple frames (logos, channel watermarks).

Features:
- Color-aware detection (not just edges)
- VRAM-adaptive sampling
- Detailed logging for debugging
- Multi-color watermark support
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Tuple, Optional

# Import tunable configuration constants
from src.infrastructure.processors import watermark_removal_config as WRC

logger = logging.getLogger(__name__)


def _detect_gpu_vram() -> float:
    """
    Detect available GPU VRAM in GB.

    Returns:
        VRAM in GB, or 0.0 if no GPU available
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return 0.0

        vram_bytes = torch.cuda.get_device_properties(0).total_memory
        vram_gb = vram_bytes / (1024 ** 3)
        return vram_gb
    except Exception:
        return 0.0


def _get_adaptive_sample_params(total_frames: int, vram_gb: float) -> Tuple[int, float]:
    """
    Get adaptive sampling parameters based on VRAM.
    Uses WRC.SAMPLE_FRAME_COUNT as base, scales with VRAM availability.

    Args:
        total_frames: Total number of frames
        vram_gb: Available VRAM in GB

    Returns:
        Tuple of (max_samples, sample_ratio)
    """
    # Base on config, then scale by VRAM
    base_samples = WRC.SAMPLE_FRAME_COUNT

    if vram_gb >= 16:
        # High VRAM (RTX 4090/5090): Process more frames for better accuracy
        max_samples = int(base_samples * 1.5)
        sample_ratio = 0.5
    elif vram_gb >= 8:
        # Medium VRAM (RTX 3080): Use config default
        max_samples = base_samples
        sample_ratio = 0.4
    elif vram_gb >= 4:
        # Low VRAM (RTX 3060): Conservative
        max_samples = int(base_samples * 0.7)
        sample_ratio = 0.3
    else:
        # Very low VRAM or CPU: Minimal
        max_samples = int(base_samples * 0.5)
        sample_ratio = 0.2

    # Don't exceed total frames
    max_samples = min(max_samples, total_frames)

    logger.info(f"VRAM: {vram_gb:.1f}GB → max_samples={max_samples}, sample_ratio={sample_ratio:.1f}")

    return max_samples, sample_ratio




def detect_static_regions(frames: List[np.ndarray],
                          persistence_threshold: float = 0.8,
                          sample_ratio: float = 0.3,
                          use_color: bool = True) -> np.ndarray:
    """
    Find regions that appear consistently across frames (static watermarks).

    Now supports COLOR-AWARE detection for colored watermarks (not just edges).

    Args:
        frames: List of BGR frames (numpy arrays)
        persistence_threshold: Ratio of frames a pixel must appear in to be considered static (0.0-1.0)
        sample_ratio: Ratio of frames to sample for detection (0.0-1.0) to speed up processing
        use_color: Use color variance detection (True) in addition to edge detection (recommended)

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

    logger.info(f"Detecting static regions: {len(sampled_frames)}/{total_frames} frames sampled")
    logger.info(f"  Persistence threshold: {persistence_threshold:.2f}")
    logger.info(f"  Color-aware detection: {'ON' if use_color else 'OFF'}")

    # Initialize accumulators
    h, w = sampled_frames[0].shape[:2]
    edge_accumulator = np.zeros((h, w), dtype=np.float32)
    color_variance_accumulator = np.zeros((h, w), dtype=np.float32)

    # Calculate mean color for variance detection
    if use_color:
        mean_frame = np.zeros((h, w, 3), dtype=np.float32)
        for frame in sampled_frames:
            mean_frame += frame.astype(np.float32)
        mean_frame /= len(sampled_frames)

    # Accumulate detections across frames
    for i, frame in enumerate(sampled_frames):
        # 1. Edge detection (for logo contours)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        edge_accumulator += (edges > 0).astype(np.float32)

        # 2. Color variance detection (for colored watermarks)
        if use_color:
            # Calculate per-pixel color distance from mean
            color_diff = np.abs(frame.astype(np.float32) - mean_frame)
            color_diff_magnitude = np.sqrt(np.sum(color_diff ** 2, axis=2))

            # Low variance = static region (watermark)
            # Threshold: pixels with <30 color distance are considered static
            static_color = (color_diff_magnitude < 30).astype(np.float32)
            color_variance_accumulator += static_color

        if (i + 1) % 10 == 0:
            logger.debug(f"  Processed {i+1}/{len(sampled_frames)} frames...")

    # Normalize accumulators to [0, 1]
    edge_accumulator /= len(sampled_frames)
    if use_color:
        color_variance_accumulator /= len(sampled_frames)

    # Combine edge and color detection
    if use_color:
        # Watermark if: high edge persistence OR high color persistence
        combined = np.maximum(edge_accumulator, color_variance_accumulator)
        logger.info(f"  Combined edge + color detection")
    else:
        combined = edge_accumulator
        logger.info(f"  Edge-only detection")

    # Threshold by persistence
    static_mask = (combined >= persistence_threshold).astype(np.uint8) * 255

    # Clean up mask (remove noise, fill holes)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    static_mask = cv2.morphologyEx(static_mask, cv2.MORPH_CLOSE, kernel)
    static_mask = cv2.morphologyEx(static_mask, cv2.MORPH_OPEN, kernel)

    # Log statistics
    coverage = np.sum(static_mask > 0) / (h * w)
    logger.info(f"✅ Static region detection complete:")
    logger.info(f"  Coverage: {coverage*100:.2f}% of frame marked as persistent")
    logger.info(f"  Resolution: {w}x{h}")

    return static_mask


def create_persistent_mask(frame_paths: List[Path],
                           roi_list: List[Tuple[int, int, int, int]],
                           persistence_threshold: float = 0.8,
                           use_color: bool = True) -> np.ndarray:
    """
    Generate unified mask for static watermarks in specified ROI zones.

    Now with VRAM-adaptive sampling and color-aware detection.

    Args:
        frame_paths: List of paths to frame images
        roi_list: List of (x, y, w, h) tuples defining ROI zones to check
        persistence_threshold: Ratio of frames a pixel must appear in
        use_color: Use color-aware detection for colored watermarks

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

    logger.info(f"=== Watermark Detection Started ===")
    logger.info(f"Frame dimensions: {w}x{h}")
    logger.info(f"Total frames: {len(frame_paths)}")
    logger.info(f"ROI zones: {len(roi_list)}")

    # VRAM-adaptive sampling
    vram_gb = _detect_gpu_vram()
    max_samples, sample_ratio = _get_adaptive_sample_params(len(frame_paths), vram_gb)

    sample_step = max(1, len(frame_paths) // max_samples)
    sampled_paths = frame_paths[::sample_step][:max_samples]

    logger.info(f"Sampling strategy: {len(sampled_paths)}/{len(frame_paths)} frames (step={sample_step})")

    # Load sampled frames
    frames = []
    failed_count = 0
    for path in sampled_paths:
        frame = cv2.imread(str(path))
        if frame is not None:
            frames.append(frame)
        else:
            failed_count += 1

    if not frames:
        logger.error("Failed to load any frames")
        return final_mask

    if failed_count > 0:
        logger.warning(f"Failed to load {failed_count}/{len(sampled_paths)} frames")

    logger.info(f"Loaded {len(frames)} frames successfully")

    # Detect static regions in each ROI
    for roi_idx, (x, y, roi_w, roi_h) in enumerate(roi_list):
        logger.info(f"--- Processing ROI {roi_idx+1}/{len(roi_list)} ---")
        logger.info(f"  Position: x={x}, y={y}, w={roi_w}, h={roi_h}")
        logger.info(f"  Area: {(roi_w*roi_h)/(w*h)*100:.1f}% of frame")

        # Extract ROI from all frames
        roi_frames = []
        for frame in frames:
            # Validate ROI bounds
            y_end = min(y + roi_h, frame.shape[0])
            x_end = min(x + roi_w, frame.shape[1])

            if y >= frame.shape[0] or x >= frame.shape[1]:
                logger.warning(f"  ROI out of bounds: ({x},{y}) for frame {frame.shape}")
                continue

            roi_crop = frame[y:y_end, x:x_end]
            if roi_crop.size > 0:
                roi_frames.append(roi_crop)

        if not roi_frames:
            logger.warning(f"  No valid ROI frames extracted for ROI {roi_idx+1}")
            continue

        # Detect static regions in this ROI with color awareness
        roi_mask = detect_static_regions(
            roi_frames,
            persistence_threshold,
            sample_ratio=sample_ratio,
            use_color=use_color
        )

        # Place ROI mask back into full frame coordinates
        roi_coverage_before = np.sum(final_mask[y:y+roi_h, x:x+roi_w] > 0) / (roi_w * roi_h)

        final_mask[y:y+roi_h, x:x+roi_w] = cv2.bitwise_or(
            final_mask[y:y+roi_h, x:x+roi_w],
            roi_mask[:roi_h, :roi_w]  # Ensure size matches
        )

        roi_coverage_after = np.sum(final_mask[y:y+roi_h, x:x+roi_w] > 0) / (roi_w * roi_h)
        roi_coverage_added = roi_coverage_after - roi_coverage_before

        logger.info(f"  ✅ ROI {roi_idx+1} complete: +{roi_coverage_added*100:.1f}% watermark detected")

    # Final cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    final_mask = cv2.morphologyEx(final_mask, cv2.MORPH_CLOSE, kernel)

    total_coverage = np.sum(final_mask > 0) / (h * w)
    logger.info(f"=== Watermark Detection Complete ===")
    logger.info(f"Total watermark coverage: {total_coverage*100:.2f}% of frame")
    logger.info(f"Total pixels marked: {np.sum(final_mask > 0):,} / {h*w:,}")

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

