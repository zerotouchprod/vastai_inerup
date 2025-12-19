"""
Geometry and math utilities for image processing.
Includes bounding box calculations, grid alignment, and safe scaling.
"""

import torch
import numpy as np
import logging

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


def select_best_roi_zone(masks: torch.Tensor, roi_height: int, border_check_rows: int = 4) -> tuple[str, int, int]:
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
