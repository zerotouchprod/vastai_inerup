"""
Mask Generator component for creating binary masks from OCR results.
Implements hybrid masking with OCR anchoring, MSER, Gradient, and ROI constraints.
"""

import logging
from typing import Optional, Tuple, List
import numpy as np
import cv2
from pathlib import Path

logger = logging.getLogger(__name__)


class MaskGenerator:
    """
    Generates binary masks for subtitle removal.
    
    Responsibilities:
    1. Logic for creating binary masks using OCR-Anchored Masking
    2. MSER/Gradient detection with OCR constraints
    3. ROI constraints and geometry filtering
    4. Safety clamping to prevent false positives
    """
    
    def __init__(self, config):
        """
        Initialize mask generator with configuration.
        
        Args:
            config: AppConfig instance containing mask settings
        """
        self.config = config
        self.mask_dilation = config.MASK_DILATION
        self.roi_str = config.ROI if config.USE_ROI_OPTIMIZATION else None
        
        logger.info(f"Mask Generator initialized (dilation={self.mask_dilation}, roi={self.roi_str})")
    
    def generate_mask(self, image: np.ndarray, ocr_results, roi_str: Optional[str] = None) -> np.ndarray:
        """
        Generate hybrid mask using OCR-Anchored Masking with ROI constraint.
        
        Args:
            image: Input BGR image
            ocr_results: List of tuples (polygon, confidence_score) from OCR engine
            roi_str: ROI string (preset or coordinates). If None, uses config ROI.
            
        Returns:
            Combined binary mask
        """
        if image is None or image.size == 0:
            logger.warning("Empty image provided to mask generator")
            h, w = 100, 100  # Default size
            return np.zeros((h, w), dtype=np.uint8)
        
        # Use provided ROI or config ROI
        effective_roi = roi_str if roi_str is not None else self.roi_str
        
        # Create OCR mask from detection results
        ocr_mask = self._create_ocr_mask(image.shape, ocr_results)
        
        # Generate hybrid mask combining OCR, MSER, and Gradient
        hybrid_mask = self._generate_hybrid_mask(image, ocr_mask, effective_roi)
        
        # Apply dilation if configured
        if self.mask_dilation > 0:
            hybrid_mask = self._apply_dilation(hybrid_mask)
        
        return hybrid_mask
    
    def _create_ocr_mask(self, image_shape, ocr_results) -> np.ndarray:
        """
        Create binary mask from OCR detection results.
        
        Args:
            image_shape: Tuple (height, width) of the image
            ocr_results: List of tuples (polygon, confidence_score)
            
        Returns:
            Binary mask with OCR-detected text regions
        """
        h, w = image_shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        if not ocr_results:
            return mask
        
        for polygon, confidence in ocr_results:
            try:

                points = polygon.astype(np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [points], 255)
            except Exception as e:
                logger.warning(f"Failed to draw OCR polygon on mask: {e}")
                continue
        
        return mask
    
    def _generate_hybrid_mask(self, image: np.ndarray, ocr_mask: np.ndarray, 
                             roi_str: Optional[str] = None) -> np.ndarray:
        """
        Generate hybrid mask using OCR-Anchored Masking with ROI constraint.
        MSER/Gradient detectors only operate within OCR-defined regions.
        
        Args:
            image: Input BGR image
            ocr_mask: Mask from PaddleOCR
            roi_str: ROI string (preset or coordinates). If provided, final mask is constrained to ROI.
            
        Returns:
            Combined binary mask
        """
        # Import here to avoid circular imports
        try:
            from src.infrastructure.image_processing.detectors import (
                get_mser_mask, get_gradient_mask, filter_mask_by_geometry, filter_subtitle_regions
            )
            from src.infrastructure.image_processing.mask_cleaning import apply_safety_clamp
            from src.infrastructure.image_processing.geometry import resolve_roi
        except ImportError as e:
            logger.error(f"Failed to import required modules: {e}")
            # Fallback to basic processing
            return self._apply_basic_processing(ocr_mask, roi_str, image.shape)
        
        # Step 1: Create "Allowed Zone" from OCR mask (dilated)
        # Dilate OCR mask to create search area (account for jumping text/OCR inaccuracies)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (30, 30))
        allowed_zone = cv2.dilate(ocr_mask, kernel, iterations=1)
        
        # Step 2: Apply MSER detection (structure layer)
        mser_mask = get_mser_mask(image)
        
        # Step 3: Apply Gradient detection (edge layer)
        gradient_mask = get_gradient_mask(image)
        
        # Step 4: Clean MSER and Gradient masks
        mser_cleaned = filter_mask_by_geometry(mser_mask)
        gradient_cleaned = filter_mask_by_geometry(gradient_mask)
        
        # Step 5: STRICT INTERSECTION - Only keep details inside Allowed Zone
        # MSER and Gradient can only operate where OCR detected something
        mser_constrained = cv2.bitwise_and(mser_cleaned, allowed_zone)
        gradient_constrained = cv2.bitwise_and(gradient_cleaned, allowed_zone)
        
        # Step 6: Combine masks (OCR is the anchor)
        combined = cv2.bitwise_or(ocr_mask, mser_constrained)
        combined = cv2.bitwise_or(combined, gradient_constrained)
        
        # Step 7: Apply safety clamp to prevent "global hallucination"
        safe_mask = apply_safety_clamp(combined, ocr_mask, safety_threshold=0.20)
        
        # Step 7.5: Apply geometry-based subtitle filtering (reject non-subtitle regions)
        if roi_str:
            safe_mask = filter_subtitle_regions(safe_mask, roi_str=roi_str)
        
        # Step 8: Apply ROI constraint if provided (HARD CONSTRAINT - "Mask Guillotine")
        if roi_str:
            h, w = image.shape[:2]
            x, y, roi_w, roi_h = resolve_roi(roi_str, w, h)
            
            # Create ROI mask (black canvas with white ROI rectangle)
            roi_mask = np.zeros_like(safe_mask)
            cv2.rectangle(roi_mask, (x, y), (x + roi_w, y + roi_h), 255, -1)
            
            # Apply hard constraint: mask ONLY inside ROI
            safe_mask = cv2.bitwise_and(safe_mask, roi_mask)
            
            # Log ROI constraint
            total_pixels = h * w
            roi_pixels = np.sum(roi_mask > 0)
            safe_pixels = np.sum(safe_mask > 0)
            
            logger.info(
                f"ROI Constraint ({roi_str}): ROI covers {roi_pixels/total_pixels*100:.1f}% of screen, "
                f"final mask covers {safe_pixels/total_pixels*100:.1f}%"
            )
        
        # Log statistics for debugging
        h, w = image.shape[:2]
        total_pixels = h * w
        ocr_coverage = np.sum(ocr_mask > 0) / total_pixels
        mser_coverage = np.sum(mser_constrained > 0) / total_pixels
        gradient_coverage = np.sum(gradient_constrained > 0) / total_pixels
        final_coverage = np.sum(safe_mask > 0) / total_pixels
        
        logger.debug(
            f"OCR-Anchored Masking: OCR={ocr_coverage*100:.1f}%, "
            f"MSER={mser_coverage*100:.1f}%, "
            f"Gradient={gradient_coverage*100:.1f}%, "
            f"Final={final_coverage*100:.1f}%"
        )
        
        return safe_mask
    
    def _apply_basic_processing(self, ocr_mask: np.ndarray, roi_str: Optional[str], 
                               image_shape: Tuple[int, int]) -> np.ndarray:
        """
        Basic fallback processing when advanced modules are not available.
        
        Args:
            ocr_mask: OCR mask
            roi_str: ROI string
            image_shape: Image shape
            
        Returns:
            Processed mask
        """
        mask = ocr_mask.copy()
        
        # Simple dilation
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
        
        # Apply ROI if specified
        if roi_str:
            from src.infrastructure.image_processing.geometry import resolve_roi
            h, w = image_shape[:2]
            x, y, roi_w, roi_h = resolve_roi(roi_str, w, h)
            
            roi_mask = np.zeros_like(mask)
            cv2.rectangle(roi_mask, (x, y), (x + roi_w, y + roi_h), 255, -1)
            mask = cv2.bitwise_and(mask, roi_mask)
        
        return mask
    
    def _apply_dilation(self, mask: np.ndarray) -> np.ndarray:
        """
        Apply dilation to mask based on configuration.
        
        Args:
            mask: Input binary mask
            
        Returns:
            Dilated mask
        """
        if self.mask_dilation <= 0:
            return mask
        
        kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=1)
        
        # Additional processing for large dilation
        if self.mask_dilation >= 8:
            dilated_mask = cv2.GaussianBlur(dilated_mask, (5, 5), 0)
        
        return dilated_mask
    
    def save_debug_visualization(self, image: np.ndarray, roi_str: str, output_path: Path, 
                                text_mask: Optional[np.ndarray] = None) -> None:
        """
        Save debug visualization showing ROI rectangle and detected text masks.
        
        Args:
            image: Input BGR image
            roi_str: ROI string (preset or coordinates)
            output_path: Path to save debug image
            text_mask: Optional binary mask of detected text (red overlay)
        """
        try:
            from src.infrastructure.image_processing.geometry import resolve_roi
        except ImportError:
            logger.warning("Cannot import resolve_roi, skipping debug visualization")
            return
        
        # Create a copy of the image for drawing
        debug_img = image.copy()
        
        # Draw ROI rectangle (green)
        h, w = image.shape[:2]
        x, y, roi_w, roi_h = resolve_roi(roi_str, w, h)
        cv2.rectangle(debug_img, (x, y), (x + roi_w, y + roi_h), (0, 255, 0), 2)
        
        # Add ROI label
        label = f"ROI: {roi_str}"
        cv2.putText(debug_img, label, (x + 5, y + 25), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Draw text mask overlay (red) if provided
        if text_mask is not None and text_mask.any():
            # Create red overlay for text regions
            red_overlay = np.zeros_like(debug_img)
            red_overlay[text_mask > 0] = (0, 0, 255)  # BGR: red
            # Blend with original image
            alpha = 0.5
            debug_img = cv2.addWeighted(debug_img, 1.0, red_overlay, alpha, 0)
            
            # Add mask info
            mask_coverage = np.sum(text_mask > 0) / (h * w) * 100
            mask_label = f"Text coverage: {mask_coverage:.1f}%"
            cv2.putText(debug_img, mask_label, (x + 5, y + 55), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        
        # Save the debug image
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), debug_img)
        logger.info(f"Saved debug visualization to {output_path}")
    
    def preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image for better OCR detection of colored/fading text.
        
        Args:
            image: Input BGR image
            
        Returns:
            Preprocessed BGR image with enhanced contrast
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply CLAHE to handle colored text on complex backgrounds
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Optional: Thresholding to isolate bright text
        _, thresh = cv2.threshold(enhanced, 200, 255, cv2.THRESH_BINARY)
        
        # Convert back to BGR (3-channel) for OCR compatibility
        bgr_thresh = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        
        return bgr_thresh
