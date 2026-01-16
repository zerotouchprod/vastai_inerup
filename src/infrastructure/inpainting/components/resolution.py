"""
Resolution calculator for ProPainterAdapter.
Handles aspect ratio preservation, downscaling logic, and dimension constraints.
"""

from typing import Tuple
from pathlib import Path
from src.core.config import AppConfig


class ResolutionCalculator:
    """Calculates target dimensions for ProPainter processing."""
    
    def __init__(self, config: AppConfig):
        self.config = config
    
    def calculate_target_dimensions(self, original_width: int, original_height: int,
                                   gpu_vram_gb: float = None) -> Tuple[int, int]:
        """
        Calculate target dimensions for ProPainter processing.
        
        Args:
            original_width: Original frame width
            original_height: Original frame height
            gpu_vram_gb: Available GPU VRAM in GB (optional)
            
        Returns:
            Tuple of (target_width, target_height)
        """
        # If AUTO_DOWNSCALE is False, use original dimensions
        if not self.config.AUTO_DOWNSCALE:
            return self.ensure_divisible_by_32(original_width, original_height)
        
        # Determine max height based on config and VRAM
        max_height = self.config.MAX_HEIGHT
        
        # Adjust max height based on VRAM if provided
        if gpu_vram_gb is not None:
            if gpu_vram_gb >= 40:
                max_height = 2160  # 4K height
            elif gpu_vram_gb >= 23:  # RTX 3090/4090
                max_height = 2160  # 4K height
            elif gpu_vram_gb >= 16:
                max_height = 1440  # 1440p height
            elif gpu_vram_gb >= 12:
                max_height = 720   # 720p height
            elif gpu_vram_gb >= 8:
                max_height = 720
            else:
                max_height = 720
        
        # Check if downscaling is needed based on height
        if original_height <= max_height:
            # No downscaling needed
            return self.ensure_divisible_by_32(original_width, original_height)
        
        # Calculate target dimensions while preserving aspect ratio
        # Scale down so that height = max_height
        scale_factor = max_height / original_height
        target_width = int(original_width * scale_factor)
        target_height = max_height
        
        # Ensure minimum dimensions
        target_width = max(target_width, 32)
        target_height = max(target_height, 32)
        
        # Make divisible by 32
        return self.ensure_divisible_by_32(target_width, target_height)
    
    def should_downscale(self, original_height: int) -> bool:
        """
        Determine if downscaling should be applied.
        
        Args:
            original_height: Original frame height
            
        Returns:
            True if downscaling should be applied
        """
        if not self.config.AUTO_DOWNSCALE:
            return False
        return original_height > self.config.MAX_HEIGHT
    
    def ensure_divisible_by_32(self, width: int, height: int) -> Tuple[int, int]:
        """
        Ensure dimensions are divisible by 32 for ProPainter compatibility.
        
        Args:
            width: Input width
            height: Input height
            
        Returns:
            Adjusted (width, height) divisible by 32
        """
        width = (width // 32) * 32
        height = (height // 32) * 32
        width = max(width, 32)
        height = max(height, 32)
        return width, height
