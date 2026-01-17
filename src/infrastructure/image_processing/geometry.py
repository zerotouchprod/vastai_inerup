"""
Geometry and math utilities for image processing.
Includes bounding box calculations, grid alignment, and safe scaling.
"""

import torch
import numpy as np
import logging
import cv2
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


def calculate_bounding_box(masks: torch.Tensor, padding: int) -> tuple[int, int, int, int]:
    """
    Calculate bounding box coordinates from mask tensor with padding and grid alignment.
    
    Args:
        masks: Mask tensor of shape (T, 1, H, W) or (H, W)
        padding: Padding in pixels to add around bounding box
        
    Returns:
        Tuple of (y1, y2, x1, x2) coordinates
    """
    # Handle different input shapes
    if masks.dim() == 4:
        # Union mask across time dimension
        union_mask = torch.max(masks, dim=0).values.squeeze(0)  # shape [H, W]
    elif masks.dim() == 3:
        # Assume shape (T, H, W) or (1, H, W)
        if masks.shape[0] == 1:
            union_mask = masks.squeeze(0)
        else:
            union_mask = torch.max(masks, dim=0).values  # shape [H, W]
    else:
        union_mask = masks  # shape [H, W]
    
    # Find non-zero indices
    non_zero = torch.nonzero(union_mask > 0, as_tuple=False)
    if len(non_zero) == 0:
        # No masks found
        return 0, 0, 0, 0
    
    # Get bounding box coordinates
    y_min, x_min = non_zero.min(dim=0).values
    y_max, x_max = non_zero.max(dim=0).values
    
    # Apply padding & grid snap (Safe Box)
    y1 = max(0, (int(y_min) - padding) // 8 * 8)
    x1 = max(0, (int(x_min) - padding) // 8 * 8)
    y2 = min(union_mask.shape[0], (int(y_max) + padding + 8) // 8 * 8)
    x2 = min(union_mask.shape[1], (int(x_max) + padding + 8) // 8 * 8)
    
    return int(y1), int(y2), int(x1), int(x2)


def align_to_grid(dimension: int, align: int = 8) -> int:
    """
    Align dimension to nearest multiple of align.
    
    Args:
        dimension: Input dimension
        align: Alignment value (default 8 for ProPainter)
        
    Returns:
        Aligned dimension
    """
    return ((dimension + align - 1) // align) * align


def calculate_safe_scale(current_area: int, max_area: int) -> float:
    """
    Calculate scale factor to fit current area within max area.
    
    Args:
        current_area: Current area in pixels
        max_area: Maximum allowed area in pixels
        
    Returns:
        Scale factor (<= 1.0)
    """
    if current_area <= max_area:
        return 1.0
    
    scale = np.sqrt(max_area / current_area)
    return min(scale, 1.0)  # Don't upscale


def calculate_crop_area_ratio(crop_h: int, crop_w: int, total_h: int, total_w: int) -> float:
    """
    Calculate crop area as ratio of total frame area.
    
    Args:
        crop_h: Crop height
        crop_w: Crop width
        total_h: Total frame height
        total_w: Total frame width
        
    Returns:
        Ratio of crop area to total area
    """
    crop_area = crop_h * crop_w
    total_area = total_h * total_w
    return crop_area / total_area if total_area > 0 else 0.0


def calculate_roi_zone_height(total_height: int, zone_height_ratio: float) -> int:
    """
    Calculate ROI zone height aligned to 8.
    
    Args:
        total_height: Total frame height
        zone_height_ratio: Ratio of zone height to total height
        
    Returns:
        ROI zone height (aligned to 8)
    """
    raw_zone_height = int(total_height * zone_height_ratio)
    roi_height = align_to_grid(raw_zone_height, 8)
    if roi_height == 0:
        roi_height = 8
    return roi_height


def get_roi_candidates(height: int, roi_height: int) -> list[tuple[str, int, int]]:
    """
    Get candidate ROI zones (top, middle, bottom).
    
    Args:
        height: Total frame height
        roi_height: Height of each ROI zone
        
    Returns:
        List of (zone_name, y_start, roi_height) tuples
    """
    candidates = []
    
    # Bottom zone
    y_bottom = height - roi_height
    candidates.append(('bottom', y_bottom, roi_height))
    
    # Top zone
    y_top = 0
    candidates.append(('top', y_top, roi_height))
    
    # Middle zone (centered)
    y_mid = (height - roi_height) // 2
    y_mid = align_to_grid(y_mid, 8)
    candidates.append(('middle', y_mid, roi_height))
    
    return candidates


def resolve_roi(roi_str: str, img_w: int, img_h: int) -> tuple[int, int, int, int]:
    """
    Returns absolute x, y, w, h for ROI.
    
    Args:
        roi_str: ROI string (preset or coordinates)
        img_w: Image width
        img_h: Image height
        
    Returns:
        Tuple of (x, y, w, h) in pixels
    """
    roi_str = roi_str.lower().strip()

    # 1. Presets
    if roi_str == 'full':
        return 0, 0, img_w, img_h
    elif roi_str == 'bottom':
        # Bottom 60% of screen (default for subtitles, including those slightly below center)
        h = int(img_h * 0.60)
        return 0, img_h - h, img_w, h
    elif roi_str == 'top':
        h = int(img_h * 0.30)
        return 0, 0, img_w, h

    # Watermark corner presets (20% of frame width/height)
    elif roi_str == 'top-left':
        return 0, 0, int(img_w * 0.2), int(img_h * 0.2)
    elif roi_str == 'top-right':
        x = int(img_w * 0.8)
        return x, 0, img_w - x, int(img_h * 0.2)
    elif roi_str == 'bottom-left':
        y = int(img_h * 0.8)
        return 0, y, int(img_w * 0.2), img_h - y
    elif roi_str == 'bottom-right':
        x, y = int(img_w * 0.8), int(img_h * 0.8)
        return x, y, img_w - x, img_h - y
    elif roi_str == 'center':
        cx, cy = int(img_w * 0.3), int(img_h * 0.3)
        cw, ch = int(img_w * 0.4), int(img_h * 0.4)
        return cx, cy, cw, ch

    # 2. Custom Coordinates "x,y,w,h"
    try:
        parts = [float(p) for p in roi_str.split(',')]
        if len(parts) != 4:
            raise ValueError(f"Invalid ROI format: {roi_str}. Expected 'x,y,w,h'")
        
        x = int(parts[0] * img_w)
        y = int(parts[1] * img_h)
        w = int(parts[2] * img_w)
        h = int(parts[3] * img_h)
        
        # Validate bounds
        if not (0.0 <= parts[0] <= 1.0 and 0.0 <= parts[1] <= 1.0 and 
                0.0 <= parts[2] <= 1.0 and 0.0 <= parts[3] <= 1.0):
            raise ValueError(f"ROI ratios must be between 0.0 and 1.0: {roi_str}")
        
        return x, y, w, h
    except Exception as e:
        logger.warning(f"Invalid ROI format '{roi_str}': {e}. Fallback to bottom (60%).")
        # Fallback to bottom preset (60%)
        h = int(img_h * 0.60)
        return 0, img_h - h, img_w, h


def resolve_multi_roi(roi_str: str, img_w: int, img_h: int) -> list[tuple[int, int, int, int]]:
    """
    Parse comma-separated ROI string into list of (x, y, w, h) tuples for multi-zone processing.

    Args:
        roi_str: ROI string - can be:
                 - Single preset: "bottom", "top-right", etc.
                 - Multi-preset: "top-right,bottom-left" (comma-separated presets)
                 - Single coordinates: "0.1,0.2,0.3,0.4" (single zone)
        img_w: Image width
        img_h: Image height

    Returns:
        List of (x, y, w, h) tuples in pixels

    Examples:
        >>> resolve_multi_roi("top-right,bottom-left", 1920, 1080)
        [(1536, 0, 384, 216), (0, 864, 384, 216)]

        >>> resolve_multi_roi("bottom", 1920, 1080)
        [(0, 594, 1920, 486)]
    """
    roi_str = roi_str.strip()

    # Check if this is a multi-preset string (contains comma and alpha characters)
    # Distinguish from single coordinate string (which also has commas but no alpha)
    parts = [p.strip() for p in roi_str.split(',')]

    # If we have more than 4 parts, or any part contains alpha chars, it's multi-preset
    has_alpha = any(any(c.isalpha() for c in part) for part in parts)

    if len(parts) > 4 or (len(parts) > 1 and has_alpha):
        # Multi-preset mode: "top-right,bottom-left"
        roi_list = []
        for preset in parts:
            try:
                roi_list.append(resolve_roi(preset, img_w, img_h))
            except Exception as e:
                logger.warning(f"Failed to resolve ROI preset '{preset}': {e}")
        return roi_list
    else:
        # Single ROI (preset or coordinates)
        return [resolve_roi(roi_str, img_w, img_h)]


def parse_roi_string(roi_str: str, width: int, height: int) -> tuple[int, int, int, int]:
    """
    Parse ROI string into pixel coordinates.
    
    Supported formats:
    - 'bottom': bottom 20% of screen (y=0.8, h=0.2)
    - 'top': top 20% of screen (y=0.0, h=0.2)
    - 'global': entire screen (x=0.0, y=0.0, w=1.0, h=1.0)
    - 'x,y,w,h': comma-separated floats (0.0-1.0), e.g., '0,0.8,1.0,0.2'
    
    Args:
        roi_str: ROI string
        width: Frame width
        height: Frame height
        
    Returns:
        Tuple of (x, y, w, h) in pixels
    """
    roi_str = roi_str.strip().lower()
    
    # Handle preset values
    if roi_str == 'bottom':
        # Bottom 20% of screen
        x = 0
        y = int(height * 0.8)
        w = width
        h = int(height * 0.2)
    elif roi_str == 'top':
        # Top 20% of screen
        x = 0
        y = 0
        w = width
        h = int(height * 0.2)
    elif roi_str == 'global':
        # Entire screen
        x = 0
        y = 0
        w = width
        h = height
    else:
        # Parse as x,y,w,h coordinates
        try:
            parts = roi_str.split(',')
            if len(parts) != 4:
                raise ValueError(f"Invalid ROI format: {roi_str}. Expected 'x,y,w,h'")
            
            x_ratio = float(parts[0])
            y_ratio = float(parts[1])
            w_ratio = float(parts[2])
            h_ratio = float(parts[3])
            
            # Validate ratios
            if not (0.0 <= x_ratio <= 1.0 and 0.0 <= y_ratio <= 1.0 and 
                    0.0 <= w_ratio <= 1.0 and 0.0 <= h_ratio <= 1.0):
                raise ValueError(f"ROI ratios must be between 0.0 and 1.0: {roi_str}")
            
            # Convert to pixels
            x = int(x_ratio * width)
            y = int(y_ratio * height)
            w = int(w_ratio * width)
            h = int(h_ratio * height)
            
        except ValueError as e:
            logger.warning(f"Failed to parse ROI string '{roi_str}': {e}. Using default 'bottom'.")
            # Fallback to bottom 20%
            x = 0
            y = int(height * 0.8)
            w = width
            h = int(height * 0.2)
    
    # Ensure ROI is within bounds
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))
    w = max(1, min(w, width - x))
    h = max(1, min(h, height - y))
    
    # Align to 8 for compatibility with ProPainter
    x = align_to_grid(x, 8)
    y = align_to_grid(y, 8)
    w = align_to_grid(w, 8)
    h = align_to_grid(h, 8)
    
    logger.info(f"ROI parsed: {roi_str} -> ({x},{y},{w},{h}) pixels")
    return x, y, w, h


def select_best_roi_zone(masks: torch.Tensor, roi_height: int, border_check_rows: int = 4) -> tuple[str | None, int, int]:
    """
    Select the best ROI zone based on mask distribution.
    
    Args:
        masks: Masks tensor of shape (T, 1, H, W)
        roi_height: Height of ROI zone
        border_check_rows: Number of rows to check at zone borders
        
    Returns:
        Tuple of (zone_type, y_start, roi_height)
        If no suitable zone found, returns (None, 0, 0)
    """
    T, _, H, W = masks.shape
    
    # Get candidate zones
    candidates = get_roi_candidates(H, roi_height)
    
    candidate_details = []
    for zone, y_start, h in candidates:
        # Extract zone masks
        zone_masks = masks[:, :, y_start:y_start+h, :]
        sum_masks = zone_masks.sum().item()
        
        # Check borders
        if zone == 'bottom':
            # Check top border of bottom zone
            border = zone_masks[:, :, 0:border_check_rows, :].sum().item()
            clean = border == 0
        elif zone == 'top':
            # Check bottom border of top zone
            border = zone_masks[:, :, -border_check_rows:, :].sum().item()
            clean = border == 0
        else:  # middle
            # Check both borders
            border_top = zone_masks[:, :, 0:border_check_rows, :].sum().item()
            border_bottom = zone_masks[:, :, -border_check_rows:, :].sum().item()
            clean = (border_top == 0) and (border_bottom == 0)
        
        candidate_details.append((zone, y_start, h, sum_masks, clean))
    
    # Decision logic
    total_sum = masks.sum().item()
    if total_sum < 10.0:
        logger.debug("No subtitles detected in frame, skipping ROI processing")
        return None, 0, 0
    
    # Find zones with mask and clean borders
    valid_zones = [(zone, y, h) for zone, y, h, s, clean in candidate_details if s > 10.0 and clean]
    
    if len(valid_zones) == 1:
        zone, y, h = valid_zones[0]
        logger.info(f"Dynamic Zone: Selected '{zone}' ROI (mask contained fully)")
        return zone, y, h
    elif len(valid_zones) > 1:
        # Multiple zones have masks, choose the one with highest sum
        best = max(candidate_details, key=lambda x: x[3] if x[3] > 10.0 and x[4] else -1)
        zone, y, h, _, _ = best
        logger.warning(
            f"Dynamic Zone: Multiple zones contain subtitles. "
            f"Choosing '{zone}' (highest mask sum)."
        )
        return zone, y, h
    else:
        # No clean zone, or masks intersect borders
        logger.warning(
            f"Dynamic Zone: No clean zone found (mask spans borders or empty). "
            f"Falling back to split‑frame processing."
        )
        return 'split', 0, 0


def dilate_mask(mask: np.ndarray, kernel_size: int = 3) -> np.ndarray:
    """
    Dilate binary mask to ensure coverage of subtitle edges.
    
    Args:
        mask: Binary mask array of shape (H, W) with values 0 or 255
        kernel_size: Size of dilation kernel (odd number)
        
    Returns:
        Dilated mask
    """
    if kernel_size <= 0:
        return mask
    
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.dilate(mask, kernel, iterations=1)


def get_roi_from_mask(
    mask: np.ndarray, 
    padding: int = 50,
    min_divisible: int = 8,
    dilate_kernel: int = 3
) -> Tuple[int, int, int, int]:
    """
    Calculate ROI bounding box from mask with padding and grid alignment.
    
    Args:
        mask: Binary mask array of shape (H, W) with values 0 or 255
        padding: Padding in pixels to add around bounding box
        min_divisible: Ensure dimensions are divisible by this value
        dilate_kernel: Kernel size for mask dilation (0 to disable)
        
    Returns:
        Tuple of (y_min, y_max, x_min, x_max) coordinates
    """
    # Dilate mask to cover edges
    if dilate_kernel > 0:
        mask = dilate_mask(mask, dilate_kernel)
    
    # Find bounding box of non-zero pixels
    nonzero = np.where(mask > 0)
    if len(nonzero[0]) == 0:
        # No mask, return empty ROI
        return 0, 0, 0, 0
    
    y_min, y_max = np.min(nonzero[0]), np.max(nonzero[0])
    x_min, x_max = np.min(nonzero[1]), np.max(nonzero[1])
    
    # Add padding
    y_min = max(0, y_min - padding)
    y_max = min(mask.shape[0], y_max + padding)
    x_min = max(0, x_min - padding)
    x_max = min(mask.shape[1], x_max + padding)
    
    # Ensure divisible by min_divisible
    y_min = (y_min // min_divisible) * min_divisible
    x_min = (x_min // min_divisible) * min_divisible
    y_max = ((y_max + min_divisible - 1) // min_divisible) * min_divisible
    x_max = ((x_max + min_divisible - 1) // min_divisible) * min_divisible
    
    # Clamp to image boundaries
    y_max = min(y_max, mask.shape[0])
    x_max = min(x_max, mask.shape[1])
    
    return int(y_min), int(y_max), int(x_min), int(x_max)


def crop_frame(frame: np.ndarray, roi: Tuple[int, int, int, int]) -> np.ndarray:
    """
    Crop region from frame using ROI coordinates.
    
    Args:
        frame: Frame array of shape (H, W, C) or (H, W)
        roi: Tuple of (y_min, y_max, x_min, x_max)
        
    Returns:
        Cropped region
    """
    y_min, y_max, x_min, x_max = roi
    if y_min >= y_max or x_min >= x_max:
        # Empty ROI
        return np.array([])
    
    return frame[y_min:y_max, x_min:x_max]


def paste_frame(
    original: np.ndarray, 
    crop: np.ndarray, 
    roi: Tuple[int, int, int, int]
) -> np.ndarray:
    """
    Paste cropped region back into original frame.
    
    Args:
        original: Original frame array
        crop: Cropped region to paste
        roi: Tuple of (y_min, y_max, x_min, x_max) where crop should be placed
        
    Returns:
        Frame with pasted region
    """
    y_min, y_max, x_min, x_max = roi
    if crop.size == 0:
        return original
    
    # Ensure crop dimensions match ROI
    crop_h, crop_w = crop.shape[:2]
    roi_h = y_max - y_min
    roi_w = x_max - x_min
    
    if crop_h != roi_h or crop_w != roi_w:
        # Resize crop to match ROI dimensions
        crop = cv2.resize(crop, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)
    
    # Create copy to avoid modifying original
    result = original.copy()
    result[y_min:y_max, x_min:x_max] = crop
    return result


def calculate_roi_area_ratio(
    roi: Tuple[int, int, int, int],
    frame_height: int,
    frame_width: int
) -> float:
    """
    Calculate ratio of ROI area to total frame area.
    
    Args:
        roi: Tuple of (y_min, y_max, x_min, x_max)
        frame_height: Total frame height
        frame_width: Total frame width
        
    Returns:
        Ratio (0.0 to 1.0)
    """
    y_min, y_max, x_min, x_max = roi
    roi_area = (y_max - y_min) * (x_max - x_min)
    total_area = frame_height * frame_width
    
    if total_area == 0:
        return 0.0
    
    return roi_area / total_area
