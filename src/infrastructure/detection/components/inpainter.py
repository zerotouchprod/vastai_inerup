"""
Inpainter component for handling OpenCV inpainting logic.
Supports Telea and Navier-Stokes algorithms with dilation and blurring.
"""

import logging
from typing import Optional
import numpy as np
import cv2

logger = logging.getLogger(__name__)


class Inpainter:
    """
    Handles OpenCV inpainting logic for subtitle removal.
    
    Responsibilities:
    1. Apply inpainting using Telea or Navier-Stokes algorithms
    2. Handle mask dilation and blurring
    3. Manage inpainting radius and quality settings
    """
    
    def __init__(self, config):
        """
        Initialize inpainter with configuration.
        
        Args:
            config: AppConfig instance containing inpainting settings
        """
        self.config = config
        self.inpainting_method = config.INPAINTING_METHOD
        self.inpainting_radius = config.INPAINTING_RADIUS
        
        logger.info(f"Inpainter initialized (method={self.inpainting_method}, radius={self.inpainting_radius})")
    
    def inpaint(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Inpaint image using the specified method.
        
        Args:
            image: Input BGR image
            mask: Binary mask where white pixels indicate regions to inpaint
            
        Returns:
            Inpainted image
        """
        if image is None or image.size == 0:
            logger.warning("Empty image provided to inpainter")
            return image
        
        if mask is None or mask.size == 0:
            logger.debug("Empty mask provided, returning original image")
            return image.copy()
        
        # Ensure mask is single-channel 8-bit
        if len(mask.shape) == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
        
        # Apply dilation to mask if configured
        if self.config.MASK_DILATION > 0:
            mask = self._apply_dilation(mask)
        
        # Apply blur to mask edges for smoother inpainting
        if self.config.MASK_BLUR > 0:
            mask = self._apply_blur(mask)
        
        # Choose inpainting method
        if self.inpainting_method == 'telea':
            result = self._inpaint_telea(image, mask)
        elif self.inpainting_method == 'ns':
            result = self._inpaint_ns(image, mask)
        else:
            logger.warning(f"Unknown inpainting method: {self.inpainting_method}, defaulting to Telea")
            result = self._inpaint_telea(image, mask)
        
        # Log statistics
        mask_coverage = np.sum(mask > 0) / (mask.shape[0] * mask.shape[1])
        logger.debug(f"Inpainting completed: {mask_coverage*100:.1f}% of image inpainted")
        
        return result
    
    def _inpaint_telea(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Apply Telea inpainting algorithm.
        
        Args:
            image: Input BGR image
            mask: Binary mask
            
        Returns:
            Inpainted image
        """
        # Telea algorithm (faster, good for small to medium regions)
        result = cv2.inpaint(
            image, mask,
            inpaintRadius=self.inpainting_radius,
            flags=cv2.INPAINT_TELEA
        )
        
        return result
    
    def _inpaint_ns(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Apply Navier-Stokes inpainting algorithm.
        
        Args:
            image: Input BGR image
            mask: Binary mask
            
        Returns:
            Inpainted image
        """
        # Navier-Stokes algorithm (slower, better for larger regions)
        result = cv2.inpaint(
            image, mask,
            inpaintRadius=self.inpainting_radius,
            flags=cv2.INPAINT_NS
        )
        
        return result
    
    def _apply_dilation(self, mask: np.ndarray) -> np.ndarray:
        """
        Apply dilation to mask.
        
        Args:
            mask: Input binary mask
            
        Returns:
            Dilated mask
        """
        kernel_size = self.config.MASK_DILATION
        kernel = np.ones((kernel_size, kernel_size), np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=1)
        
        return dilated_mask
    
    def _apply_blur(self, mask: np.ndarray) -> np.ndarray:
        """
        Apply Gaussian blur to mask edges.
        
        Args:
            mask: Input binary mask
            
        Returns:
            Blurred mask
        """
        blur_size = self.config.MASK_BLUR
        # Ensure odd kernel size
        if blur_size % 2 == 0:
            blur_size += 1
        
        blurred_mask = cv2.GaussianBlur(mask, (blur_size, blur_size), 0)
        
        # Re-threshold to maintain binary nature
        _, blurred_mask = cv2.threshold(blurred_mask, 127, 255, cv2.THRESH_BINARY)
        
        return blurred_mask
    
    def inpaint_frame(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        Alias for inpaint method for compatibility with facade.
        
        Args:
            image: Input BGR image
            mask: Binary mask
            
        Returns:
            Inpainted image
        """
        return self.inpaint(image, mask)
    
    def batch_inpaint(self, images: list, masks: list) -> list:
        """
        Inpaint a batch of images.
        
        Args:
            images: List of BGR images
            masks: List of binary masks
            
        Returns:
            List of inpainted images
        """
        if len(images) != len(masks):
            raise ValueError(f"Number of images ({len(images)}) and masks ({len(masks)}) must match")
        
        results = []
        for i, (image, mask) in enumerate(zip(images, masks)):
            try:
                result = self.inpaint(image, mask)
                results.append(result)
                
                if i % 10 == 0:
                    logger.debug(f"Batch inpainting progress: {i+1}/{len(images)}")
            except Exception as e:
                logger.error(f"Failed to inpaint image {i}: {e}")
                # Fallback to original image
                results.append(image.copy())
        
        return results
