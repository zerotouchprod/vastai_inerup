"""
Abstract interfaces for text detection components.
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class TextDetector(ABC):
    """
    Abstract base class for text detection engines.
    Each detector must implement a `detect` method that returns a binary mask.
    """
    
    @abstractmethod
    def detect(self, image: np.ndarray) -> np.ndarray:
        """
        Detect text regions in an image and return a binary mask.
        
        Args:
            image: Input image in BGR format (numpy array, uint8).
            
        Returns:
            Binary mask where text regions are marked with 255 (white)
            and background with 0 (black). Same dimensions as input image.
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the detector is available (e.g., required libraries loaded).
        
        Returns:
            True if the detector can be used, False otherwise.
        """
        pass
