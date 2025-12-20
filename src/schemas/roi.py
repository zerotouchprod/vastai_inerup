"""
Region of Interest (ROI) data models for image processing.
Uses Pydantic for strict validation of normalized coordinates (0.0-1.0).
"""

from pydantic import BaseModel, Field, model_validator
from typing import Optional


class RegionOfInterest(BaseModel):
    """
    Normalized coordinates of a region of interest (0.0 - 1.0).
    Origin (0,0) is at the top-left corner of the image.
    
    Example:
        RegionOfInterest(x=0.1, y=0.6, width=0.8, height=0.3)
        This defines a region starting at 10% from left, 60% from top,
        covering 80% width and 30% height of the image.
    """
    x: float = Field(..., ge=0.0, le=1.0, description="Left offset (x_min)")
    y: float = Field(..., ge=0.0, le=1.0, description="Top offset (y_min)")
    width: float = Field(..., gt=0.0, le=1.0, description="Region width")
    height: float = Field(..., gt=0.0, le=1.0, description="Region height")

    @model_validator(mode='after')
    def check_boundaries(self) -> 'RegionOfInterest':
        """
        Validate that the region stays within image boundaries.
        Allows small floating-point errors (0.0001 tolerance).
        """
        if self.x + self.width > 1.0001:  # 0.0001 tolerance for float errors
            raise ValueError(
                f"Region X+Width ({self.x + self.width:.4f}) exceeds 1.0. "
                f"X={self.x:.4f}, Width={self.width:.4f}"
            )
        if self.y + self.height > 1.0001:
            raise ValueError(
                f"Region Y+Height ({self.y + self.height:.4f}) exceeds 1.0. "
                f"Y={self.y:.4f}, Height={self.height:.4f}"
            )
        return self
    
    def to_pixel_coordinates(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        """
        Convert normalized coordinates to absolute pixel coordinates.
        Uses rounding to handle floating-point precision issues.
        
        Args:
            image_width: Width of the image in pixels
            image_height: Height of the image in pixels
            
        Returns:
            Tuple of (left, top, right, bottom) pixel coordinates
        """
        left = int(round(self.x * image_width))
        top = int(round(self.y * image_height))
        right = int(round((self.x + self.width) * image_width))
        bottom = int(round((self.y + self.height) * image_height))
        
        # Ensure coordinates are within bounds
        left = max(0, min(left, image_width - 1))
        top = max(0, min(top, image_height - 1))
        right = max(left + 1, min(right, image_width))
        bottom = max(top + 1, min(bottom, image_height))
        
        return left, top, right, bottom
    
    @classmethod
    def from_string(cls, roi_str: str) -> 'RegionOfInterest':
        """
        Create RegionOfInterest from string format "x,y,width,height".
        
        Args:
            roi_str: String in format "x,y,width,height" (e.g., "0.1,0.6,0.8,0.3")
            
        Returns:
            RegionOfInterest instance
            
        Raises:
            ValueError: If string format is invalid
        """
        try:
            parts = roi_str.split(',')
            if len(parts) != 4:
                raise ValueError(f"Invalid ROI format: {roi_str}. Expected 'x,y,width,height'")
            
            x = float(parts[0])
            y = float(parts[1])
            width = float(parts[2])
            height = float(parts[3])
            
            return cls(x=x, y=y, width=width, height=height)
        except ValueError as e:
            raise ValueError(f"Failed to parse ROI string '{roi_str}': {e}")


class ROIRequest(BaseModel):
    """
    Request model for ROI processing.
    Contains the ROI definition and optional processing parameters.
    """
    roi: RegionOfInterest
    image_path: Optional[str] = Field(None, description="Path to image file")
    image_bytes: Optional[bytes] = Field(None, description="Image data as bytes")
    preserve_aspect_ratio: bool = Field(True, description="Whether to preserve aspect ratio when resizing")
    output_format: str = Field("JPEG", description="Output format (JPEG, PNG, etc.)")
    
    @model_validator(mode='after')
    def check_image_source(self) -> 'ROIRequest':
        """Ensure at least one image source is provided."""
        if not self.image_path and not self.image_bytes:
            raise ValueError("Either image_path or image_bytes must be provided")
        return self


class ROIResponse(BaseModel):
    """
    Response model for ROI processing.
    Contains the cropped image and metadata.
    """
    success: bool
    cropped_image_bytes: Optional[bytes] = None
    original_size: tuple[int, int]
    cropped_size: tuple[int, int]
    roi_coordinates: tuple[int, int, int, int]  # left, top, right, bottom
    error_message: Optional[str] = None
