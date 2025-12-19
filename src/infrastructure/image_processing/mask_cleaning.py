"""
Mask cleaning module for removing noise and false positives from text detection.
Filters connected components based on geometry to prevent "global hallucination".
"""

import cv2
import numpy as np
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)


def clean_mask(mask: np.ndarray, max_blob_area_ratio: float = 0.01) -> np.ndarray:
    """
    Clean mask by filtering connected components based on geometric properties.
    
    Args:
        mask: Binary mask (0 or 255) of shape (H, W)
        max_blob_area_ratio: Maximum allowed blob area as ratio of total image area
        
    Returns:
        Cleaned binary mask with noise removed
    """
    if mask is None or mask.size == 0:
        return mask
    
    # Ensure mask is binary (0 or 255)
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    
    # Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    
    if num_labels <= 1:  # Only background
        return mask
    
    H, W = mask.shape
    total_area = H * W
    max_blob_area = int(total_area * max_blob_area_ratio)
    
    # Create output mask
    cleaned_mask = np.zeros_like(mask)
    
    # Filter components (skip background at index 0)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        
        # Skip if area is too small (noise)
        if area < 10:
            continue
        
        # Skip if area is too large (background lines, not text)
        if area > max_blob_area:
            logger.debug(f"Filtered blob {i}: area {area} > max {max_blob_area}")
            continue
        
        # Calculate aspect ratio
        if w > 0 and h > 0:
            aspect_ratio = h / w
            
            # Skip vertical lines (manga panel lines, not subtitles)
            # Subtitles are horizontal, so aspect ratio should be < 5
            if aspect_ratio > 5:
                logger.debug(f"Filtered blob {i}: vertical line (aspect ratio {aspect_ratio:.1f})")
                continue
            
            # Skip horizontal lines that are too thin (likely background lines)
            if aspect_ratio < 0.2 and h < 3:
                logger.debug(f"Filtered blob {i}: too thin horizontal line (height {h})")
                continue
        
        # Calculate solidity (area / convex hull area)
        # Text has high solidity, scattered noise has low solidity
        component_mask = (labels == i).astype(np.uint8) * 255
        contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            contour = contours[0]
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            
            if hull_area > 0:
                solidity = area / hull_area
                
                # Skip scattered noise (text is solid)
                if solidity < 0.2:
                    logger.debug(f"Filtered blob {i}: scattered noise (solidity {solidity:.2f})")
                    continue
        
        # Component passed all filters, keep it
        cleaned_mask[labels == i] = 255
    
    # Log statistics
    original_pixels = np.sum(mask > 0)
    cleaned_pixels = np.sum(cleaned_mask > 0)
    removed_pixels = original_pixels - cleaned_pixels
    
    if removed_pixels > 0:
        logger.info(
            f"Mask cleaning: removed {removed_pixels} pixels ({removed_pixels/original_pixels*100:.1f}%) "
            f"from {num_labels-1} blobs"
        )
    
    return cleaned_mask


def apply_safety_clamp(
    hybrid_mask: np.ndarray, 
    ocr_mask: np.ndarray, 
    safety_threshold: float = 0.20
) -> np.ndarray:
    """
    Apply safety clamp to prevent "global hallucination".
    
    If the hybrid mask covers too much of the screen (> safety_threshold),
    fall back to only trusting the OCR mask (dilated).
    
    Args:
        hybrid_mask: Combined mask from OCR + MSER + Gradient
        ocr_mask: Original OCR mask (AI-based, more reliable)
        safety_threshold: Maximum allowed coverage ratio (0.0-1.0)
        
    Returns:
        Safe mask that won't cover too much of the screen
    """
    if hybrid_mask is None or ocr_mask is None:
        return hybrid_mask
    
    H, W = hybrid_mask.shape
    total_pixels = H * W
    
    # Calculate coverage
    hybrid_coverage = np.sum(hybrid_mask > 0) / total_pixels
    
    if hybrid_coverage <= safety_threshold:
        # Coverage is safe, return hybrid mask
        return hybrid_mask
    
    # Coverage exceeds safety threshold - panic mode!
    logger.warning(
        f"Safety clamp triggered: hybrid mask covers {hybrid_coverage*100:.1f}% of screen "
        f"(>{safety_threshold*100:.0f}%). Falling back to OCR-only mask."
    )
    
    # Dilate OCR mask slightly to maintain coverage
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    ocr_dilated = cv2.dilate(ocr_mask, kernel, iterations=1)
    
    # Calculate OCR coverage after dilation
    ocr_coverage = np.sum(ocr_dilated > 0) / total_pixels
    logger.info(f"OCR-only mask covers {ocr_coverage*100:.1f}% of screen")
    
    return ocr_dilated


def filter_mask_by_geometry(mask: np.ndarray) -> np.ndarray:
    """
    Filter mask by geometry (legacy function for compatibility).
    This is a wrapper around clean_mask with default parameters.
    
    Args:
        mask: Binary mask (0 or 255) of shape (H, W)
        
    Returns:
        Filtered binary mask
    """
    return clean_mask(mask, max_blob_area_ratio=0.01)


def clean_mask_with_stats(mask: np.ndarray) -> Tuple[np.ndarray, dict]:
    """
    Clean mask and return statistics about the cleaning process.
    
    Args:
        mask: Binary mask (0 or 255) of shape (H, W)
        
    Returns:
        Tuple of (cleaned_mask, stats_dict)
    """
    if mask is None or mask.size == 0:
        return mask, {}
    
    # Get original stats
    H, W = mask.shape
    total_area = H * W
    original_pixels = np.sum(mask > 0)
    
    # Clean mask
    cleaned_mask = clean_mask(mask)
    cleaned_pixels = np.sum(cleaned_mask > 0)
    
    # Calculate statistics
    stats = {
        'original_pixels': original_pixels,
        'cleaned_pixels': cleaned_pixels,
        'removed_pixels': original_pixels - cleaned_pixels,
        'original_coverage': original_pixels / total_area,
        'cleaned_coverage': cleaned_pixels / total_area,
        'reduction_percent': (original_pixels - cleaned_pixels) / original_pixels * 100 if original_pixels > 0 else 0
    }
    
    return cleaned_mask, stats
