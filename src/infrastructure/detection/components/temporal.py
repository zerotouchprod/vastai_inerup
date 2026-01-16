"""
Temporal Filter component for applying temporal consistency to masks.
Implements sliding window logic for mask consistency (removing flickering).
"""

import logging
from typing import List, Optional
import numpy as np
import cv2

logger = logging.getLogger(__name__)


class TemporalFilter:
    """
    Applies temporal filtering to masks for consistent subtitle removal.
    
    Responsibilities:
    1. Handling sliding window logic for mask consistency
    2. Removing flickering between frames
    3. Temporal voting and validation
    """
    
    def __init__(self, window_size: int = 2):
        """
        Initialize temporal filter with window size.
        
        Args:
            window_size: Size of sliding window (frames before and after)
        """
        self.window_size = window_size
        logger.info(f"Temporal Filter initialized (window_size={window_size})")
    
    def apply_consistency(self, mask_buffer: List[np.ndarray]) -> np.ndarray:
        """
        Apply temporal consistency to the current mask using sliding window.
        
        Args:
            mask_buffer: List of masks in the temporal window
            
        Returns:
            Temporally consistent mask
        """
        if not mask_buffer:
            logger.warning("Empty mask buffer provided")
            return np.zeros((100, 100), dtype=np.uint8)
        
        # Combine masks in the window using logical OR (max)
        combined_mask = mask_buffer[0].copy()
        for mask in mask_buffer[1:]:
            combined_mask = cv2.bitwise_or(combined_mask, mask)
        
        return combined_mask
    
    def process_batch(self, masks: List[np.ndarray]) -> List[np.ndarray]:
        """
        Process batch of masks with temporal smearing.
        
        Args:
            masks: List of masks for consecutive frames
            
        Returns:
            List of temporally smoothed masks
        """
        if not masks:
            return []
        
        smeared_masks = []
        
        for i in range(len(masks)):
            # Get indices for the window
            start_idx = max(0, i - self.window_size)
            end_idx = min(len(masks), i + self.window_size + 1)
            
            # Combine masks in the window using logical OR (max)
            window_masks = masks[start_idx:end_idx]
            if window_masks:
                combined_mask = window_masks[0].copy()
                for mask in window_masks[1:]:
                    combined_mask = cv2.bitwise_or(combined_mask, mask)
                smeared_masks.append(combined_mask)
            else:
                smeared_masks.append(masks[i])
        
        return smeared_masks
    
    def apply_temporal_validation(self, masks: List[np.ndarray], 
                                 min_votes: int = 2) -> List[np.ndarray]:
        """
        Apply temporal consistency validation (voting filter).
        Reject isolated detections that appear in fewer than min_votes frames.
        
        Args:
            masks: List of masks for consecutive frames
            min_votes: Minimum number of frames where pixel must appear
            
        Returns:
            List of validated masks
        """
        if not masks:
            return []
        
        validated_masks = []
        
        for i, mask in enumerate(masks):
            # Count how many frames in the window have this pixel lit
            window_start = max(0, i - self.window_size)
            window_end = min(len(masks), i + self.window_size + 1)
            
            # Create voting map: count occurrences of each pixel across window
            pixel_votes = np.zeros_like(mask, dtype=np.uint8)
            for j in range(window_start, window_end):
                pixel_votes += (masks[j] > 0).astype(np.uint8)
            
            # Keep only pixels that appear in at least min_votes frames
            validated_mask = ((pixel_votes >= min_votes).astype(np.uint8) * 255)
            validated_masks.append(validated_mask)
            
            # Log validation statistics
            if i % 10 == 0:
                original_coverage = np.sum(mask > 0) / (mask.shape[0] * mask.shape[1])
                validated_coverage = np.sum(validated_mask > 0) / (mask.shape[0] * mask.shape[1])
                logger.debug(
                    f"Frame {i}: Temporal validation removed "
                    f"{(original_coverage - validated_coverage) * 100:.1f}% isolated pixels"
                )
        
        return validated_masks
    
    def smooth_masks(self, masks: List[np.ndarray], 
                    method: str = 'median') -> List[np.ndarray]:
        """
        Apply smoothing to masks using specified method.
        
        Args:
            masks: List of masks
            method: Smoothing method ('median', 'gaussian', 'average')
            
        Returns:
            List of smoothed masks
        """
        if not masks:
            return []
        
        smoothed_masks = []
        
        for mask in masks:
            if method == 'median':
                # Median filter to remove noise
                smoothed = cv2.medianBlur(mask, 3)
            elif method == 'gaussian':
                # Gaussian blur for soft edges
                smoothed = cv2.GaussianBlur(mask, (3, 3), 0)
            elif method == 'average':
                # Average filter
                kernel = np.ones((3, 3), np.float32) / 9
                smoothed = cv2.filter2D(mask, -1, kernel)
            else:
                smoothed = mask
            
            # Convert back to binary
            _, smoothed = cv2.threshold(smoothed, 127, 255, cv2.THRESH_BINARY)
            smoothed_masks.append(smoothed)
        
        return smoothed_masks
