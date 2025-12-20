"""
Computer Vision based text detector using morphological operations.
"""

import logging
import numpy as np
import cv2

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    Text detector that uses pure Computer Vision (morphological operations)
    to find text-like regions based on texture and shape.
    
    Features:
    - CLAHE contrast enhancement for dark/colored text.
    - Morphological gradient to detect edges.
    - Adaptive thresholding for binarization.
    - Horizontal smearing to connect letters into lines.
    - Aspect ratio filtering to keep only subtitle-like regions.
    """
    
    def __init__(self, mask_dilation: int = 15):
        """
        Initialize CV engine.
        
        Args:
            mask_dilation: Dilation radius for final mask (default: 15)
        """
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (dilation={mask_dilation})")
    
    def detect(self, image: np.ndarray) -> np.ndarray:
        """
        Detect text regions using morphological operations.
        
        Args:
            image: Input image in BGR format.
            
        Returns:
            Binary mask where detected text regions are white (255).
        """
        try:
            mask = self._morphological_text_hunter(image)
            
            # Apply dilation if configured
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(
                    cv2.MORPH_RECT, 
                    (self.mask_dilation, self.mask_dilation)
                )
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            return mask
            
        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            # Return empty mask on error
            return np.zeros(image.shape[:2], dtype=np.uint8)
    
    def _morphological_text_hunter(self, image: np.ndarray) -> np.ndarray:
        """
        Pure Computer Vision approach using CLAHE + Adaptive Thresholding + Morphology.
        Finds text regions based on texture density and horizontal alignment.
        """
        # 1. Convert to Gray
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # CRITICAL: This pulls details out of dark/colored regions
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 3. Compute Morphological Gradient (Edginess)
        kernel_grad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        grad = cv2.morphologyEx(enhanced, cv2.MORPH_GRADIENT, kernel_grad)

        # 4. Binarize using Adaptive Threshold (Better for gradients than Otsu)
        binary = cv2.adaptiveThreshold(
            grad, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 5. Connect Horizontally (Smear)
        # Text is horizontal. We bridge gaps between letters.
        # Kernel: (30, 1) -> Connect things up to 30px apart horizontally
        kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
        connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_connect)

        # 6. Filter by shape (Keep only bar-like shapes)
        contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        mask = np.zeros_like(gray)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)

            # Subtitle Logic:
            # - Must be somewhat wide (AR > 1.5)
            # - Must not be too small (w > 15, h > 8)
            # - Must not be the whole screen (h < image_h / 3)
            if aspect_ratio > 1.5 and w > 15 and h > 8 and h < (image.shape[0] / 3):
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

        # 7. Dilate final mask slightly to ensure full coverage
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 5))
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)

        return mask
    
    def is_available(self) -> bool:
        """
        Check if CV engine is available (always True as it only depends on OpenCV).
        
        Returns:
            True (CV engine is always available if OpenCV is installed).
        """
        return True
