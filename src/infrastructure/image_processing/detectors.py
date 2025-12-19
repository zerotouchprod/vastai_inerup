"""
Universal text detectors for subtitle removal.
Includes MSER (Maximally Stable Extremal Regions) and Gradient Morphology
for color-agnostic text detection.
"""

import cv2
import numpy as np
import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)


def get_mser_mask(image: np.ndarray, 
                  delta: int = 5,
                  min_area: int = 100,
                  max_area: int = 10000,
                  max_variation: float = 0.25,
                  min_diversity: float = 0.2) -> np.ndarray:
    """
    Detect text regions using MSER (Maximally Stable Extremal Regions).
    MSER finds connected components that stay stable over intensity thresholds.
    
    Args:
        image: Input BGR image
        delta: Intensity step size for stability calculation
        min_area: Minimum area of detected region
        max_area: Maximum area of detected region
        max_variation: Maximum variation of region stability
        min_diversity: Minimum diversity between regions
        
    Returns:
        Binary mask of detected text regions (uint8, 0-255)
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Create MSER detector
    mser = cv2.MSER_create(
        delta=delta,
        min_area=min_area,
        max_area=max_area,
        max_variation=max_variation,
        min_diversity=min_diversity
    )
    
    # Detect regions
    regions, _ = mser.detectRegions(gray)
    
    # Create empty mask
    mask = np.zeros(gray.shape, dtype=np.uint8)
    
    if len(regions) == 0:
        return mask
    
    # Filter regions by aspect ratio and area to keep only text-like regions
    h, w = gray.shape
    max_screen_area = h * w * 0.05  # Max 5% of screen area
    
    for region in regions:
        # Get convex hull of region
        hull = cv2.convexHull(region.reshape(-1, 1, 2))
        
        # Calculate bounding rectangle
        x, y, rw, rh = cv2.boundingRect(hull)
        
        # Calculate aspect ratio
        aspect_ratio = max(rw, rh) / (min(rw, rh) + 1e-6)
        
        # Calculate area
        area = rw * rh
        
        # Filter criteria for text-like regions:
        # 1. Aspect ratio between 0.2 and 3.0 (text is usually not too elongated)
        # 2. Area less than 5% of screen (text regions are relatively small)
        # 3. Width and height not too small (avoid noise)
        if (0.2 <= aspect_ratio <= 3.0 and 
            area <= max_screen_area and
            rw >= 5 and rh >= 5):
            
            # Draw convex hull on mask
            cv2.fillConvexPoly(mask, hull, 255)
    
    # Apply morphological operations to clean up the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    logger.debug(f"MSER detected {len(regions)} regions, kept {np.sum(mask > 0) / 255:.0f} pixels")
    return mask


def get_gradient_mask(image: np.ndarray,
                      kernel_size: Tuple[int, int] = (3, 3),
                      threshold: int = 40) -> np.ndarray:
    """
    Detect text edges using morphological gradient.
    Subtitles have sharp edges compared to blurred backgrounds.
    
    Args:
        image: Input BGR image
        kernel_size: Size of morphological kernel
        threshold: Threshold for binarizing gradient magnitude
        
    Returns:
        Binary mask of detected edges (uint8, 0-255)
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply morphological gradient: dilate - erode
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
    morph_grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
    
    # Threshold to get binary mask
    _, mask = cv2.threshold(morph_grad, threshold, 255, cv2.THRESH_BINARY)
    
    # Apply morphological closing to connect nearby edges
    closing_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, closing_kernel)
    
    # Remove small noise
    opening_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, opening_kernel)
    
    logger.debug(f"Gradient mask has {np.sum(mask > 0) / 255:.0f} pixels")
    return mask


def get_hybrid_mask(image: np.ndarray,
                    ocr_mask: np.ndarray,
                    use_mser: bool = True,
                    use_gradient: bool = True,
                    mser_params: dict = None,
                    gradient_params: dict = None) -> np.ndarray:
    """
    Combine multiple detection methods for universal text detection.
    
    Args:
        image: Input BGR image
        ocr_mask: Mask from PaddleOCR (semantic detection)
        use_mser: Whether to use MSER detection
        use_gradient: Whether to use gradient detection
        mser_params: Parameters for MSER detector
        gradient_params: Parameters for gradient detector
        
    Returns:
        Combined binary mask (uint8, 0-255)
    """
    # Start with OCR mask
    combined = ocr_mask.copy()
    
    # Apply MSER detection if enabled
    if use_mser:
        mser_defaults = {'delta': 5, 'min_area': 100, 'max_area': 10000}
        if mser_params:
            mser_defaults.update(mser_params)
        
        mser_mask = get_mser_mask(image, **mser_defaults)
        combined = cv2.bitwise_or(combined, mser_mask)
    
    # Apply gradient detection if enabled
    if use_gradient:
        gradient_defaults = {'kernel_size': (3, 3), 'threshold': 40}
        if gradient_params:
            gradient_defaults.update(gradient_params)
        
        gradient_mask = get_gradient_mask(image, **gradient_defaults)
        combined = cv2.bitwise_or(combined, gradient_mask)
    
    # Apply morphological operations to clean up combined mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    
    # Fill small holes
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
    
    logger.debug(f"Hybrid mask has {np.sum(combined > 0) / 255:.0f} pixels "
                 f"(OCR: {np.sum(ocr_mask > 0) / 255:.0f})")
    
    return combined


def filter_mask_by_geometry(mask: np.ndarray,
                            min_aspect_ratio: float = 0.2,
                            max_aspect_ratio: float = 3.0,
                            min_area: int = 50,
                            max_area_ratio: float = 0.05) -> np.ndarray:
    """
    Filter mask regions based on geometric properties.
    
    Args:
        mask: Input binary mask
        min_aspect_ratio: Minimum aspect ratio for valid regions
        max_aspect_ratio: Maximum aspect ratio for valid regions
        min_area: Minimum area in pixels
        max_area_ratio: Maximum area as ratio of total image area
        
    Returns:
        Filtered binary mask
    """
    h, w = mask.shape
    total_area = h * w
    max_area = int(total_area * max_area_ratio)
    
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Create new mask
    filtered = np.zeros_like(mask)
    
    for contour in contours:
        # Get bounding rectangle
        x, y, rw, rh = cv2.boundingRect(contour)
        area = rw * rh
        
        # Calculate aspect ratio
        aspect_ratio = max(rw, rh) / (min(rw, rh) + 1e-6)
        
        # Apply filters
        if (min_area <= area <= max_area and
            min_aspect_ratio <= aspect_ratio <= max_aspect_ratio):
            
            # Draw filled contour
            cv2.drawContours(filtered, [contour], -1, 255, -1)
    
    return filtered


def enhance_contrast_for_detection(image: np.ndarray) -> np.ndarray:
    """
    Enhance image contrast for better text detection.
    
    Args:
        image: Input BGR image
        
    Returns:
        Contrast-enhanced BGR image
    """
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Convert back to BGR
    enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    
    return enhanced_bgr
