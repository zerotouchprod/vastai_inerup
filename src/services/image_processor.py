"""
Image processing service for Region of Interest (ROI) operations.
Provides functionality to crop images based on normalized coordinates.
"""

import logging
from pathlib import Path
from typing import Optional, Union
from io import BytesIO

from PIL import Image, UnidentifiedImageError
from src.schemas.roi import RegionOfInterest, ROIRequest, ROIResponse


logger = logging.getLogger(__name__)


class ImageProcessingError(Exception):
    """Custom exception for image processing errors."""
    pass


class ImageService:
    """Service for image processing operations with ROI support."""
    
    @staticmethod
    def crop_image(
        image: Union[Image.Image, bytes, str, Path],
        roi: RegionOfInterest,
        output_format: str = "JPEG",
        quality: int = 95
    ) -> Image.Image:
        """
        Crop an image based on normalized ROI coordinates.
        
        Args:
            image: Input image as PIL Image, bytes, file path, or Path object
            roi: RegionOfInterest defining the crop area (normalized coordinates 0.0-1.0)
            output_format: Format for the output image (JPEG, PNG, etc.)
            quality: Quality for JPEG output (1-100)
            
        Returns:
            Cropped PIL Image
            
        Raises:
            ImageProcessingError: If image cannot be loaded or processed
            ValueError: If ROI coordinates are invalid
        """
        try:
            # Load image if not already a PIL Image
            if not isinstance(image, Image.Image):
                pil_image = ImageService._load_image(image)
            else:
                pil_image = image
            
            # Get image dimensions
            img_w, img_h = pil_image.size
            logger.info(f"Original image size: {img_w}x{img_h} pixels")
            
            # Convert normalized coordinates to pixel coordinates
            left, top, right, bottom = roi.to_pixel_coordinates(img_w, img_h)
            logger.info(f"ROI pixel coordinates: left={left}, top={top}, right={right}, bottom={bottom}")
            
            # Validate pixel coordinates
            if left >= right or top >= bottom:
                raise ValueError(
                    f"Invalid ROI pixel coordinates: "
                    f"left={left}, right={right}, top={top}, bottom={bottom}"
                )
            
            if left < 0 or top < 0 or right > img_w or bottom > img_h:
                raise ValueError(
                    f"ROI coordinates out of bounds: "
                    f"image={img_w}x{img_h}, ROI=({left},{top},{right},{bottom})"
                )
            
            # Perform cropping
            cropped_image = pil_image.crop((left, top, right, bottom))
            
            # Log result
            crop_w, crop_h = cropped_image.size
            logger.info(f"Cropped image size: {crop_w}x{crop_h} pixels")
            
            return cropped_image
            
        except UnidentifiedImageError as e:
            raise ImageProcessingError(f"Cannot identify image file: {e}")
        except (IOError, OSError) as e:
            raise ImageProcessingError(f"Cannot load or process image: {e}")
        except Exception as e:
            raise ImageProcessingError(f"Unexpected error during image cropping: {e}")
    
    @staticmethod
    def process_roi_request(request: ROIRequest) -> ROIResponse:
        """
        Process a complete ROI request.
        
        Args:
            request: ROIRequest containing image source and ROI definition
            
        Returns:
            ROIResponse with cropped image and metadata
        """
        try:
            # Load image from either path or bytes
            if request.image_path:
                image_source = request.image_path
            else:
                image_source = request.image_bytes
            
            # Crop image
            cropped_image = ImageService.crop_image(
                image=image_source,
                roi=request.roi,
                output_format=request.output_format
            )
            
            # Get original image size for metadata
            if request.image_path:
                with Image.open(request.image_path) as img:
                    original_size = img.size
            else:
                with Image.open(BytesIO(request.image_bytes)) as img:
                    original_size = img.size
            
            # Convert cropped image to bytes
            output_buffer = BytesIO()
            cropped_image.save(
                output_buffer,
                format=request.output_format,
                quality=95,
                optimize=True
            )
            cropped_bytes = output_buffer.getvalue()
            
            # Get ROI pixel coordinates
            left, top, right, bottom = request.roi.to_pixel_coordinates(
                original_size[0], original_size[1]
            )
            
            return ROIResponse(
                success=True,
                cropped_image_bytes=cropped_bytes,
                original_size=original_size,
                cropped_size=cropped_image.size,
                roi_coordinates=(left, top, right, bottom),
                error_message=None
            )
            
        except Exception as e:
            logger.error(f"ROI processing failed: {e}", exc_info=True)
            return ROIResponse(
                success=False,
                cropped_image_bytes=None,
                original_size=(0, 0),
                cropped_size=(0, 0),
                roi_coordinates=(0, 0, 0, 0),
                error_message=str(e)
            )
    
    @staticmethod
    def _load_image(image_source: Union[bytes, str, Path]) -> Image.Image:
        """
        Load image from various sources.
        
        Args:
            image_source: Image as bytes, file path string, or Path object
            
        Returns:
            PIL Image object
            
        Raises:
            ImageProcessingError: If image cannot be loaded
        """
        try:
            if isinstance(image_source, bytes):
                return Image.open(BytesIO(image_source))
            else:
                # Convert to string path if it's a Path object
                path_str = str(image_source) if isinstance(image_source, Path) else image_source
                return Image.open(path_str)
        except (IOError, OSError, UnidentifiedImageError) as e:
            raise ImageProcessingError(f"Cannot load image from source: {e}")
    
    @staticmethod
    def save_image(
        image: Image.Image,
        output_path: Union[str, Path],
        output_format: Optional[str] = None,
        quality: int = 95
    ) -> None:
        """
        Save image to file.
        
        Args:
            image: PIL Image to save
            output_path: Path where to save the image
            output_format: Format to save as (JPEG, PNG, etc.)
            quality: Quality for JPEG output (1-100)
            
        Raises:
            ImageProcessingError: If image cannot be saved
        """
        try:
            # Determine format from extension if not specified
            if output_format is None:
                output_path_str = str(output_path)
                if output_path_str.lower().endswith('.png'):
                    output_format = 'PNG'
                elif output_path_str.lower().endswith('.jpg') or output_path_str.lower().endswith('.jpeg'):
                    output_format = 'JPEG'
                else:
                    output_format = 'JPEG'  # Default
            
            # Convert Path to string if needed
            path_str = str(output_path) if isinstance(output_path, Path) else output_path
            
            # Save image
            image.save(
                path_str,
                format=output_format,
                quality=quality,
                optimize=True
            )
            logger.info(f"Image saved to: {path_str} ({output_format}, {image.size[0]}x{image.size[1]})")
            
        except (IOError, OSError) as e:
            raise ImageProcessingError(f"Cannot save image to {output_path}: {e}")
    
    @staticmethod
    def image_to_bytes(
        image: Image.Image,
        output_format: str = "JPEG",
        quality: int = 95
    ) -> bytes:
        """
        Convert PIL Image to bytes.
        
        Args:
            image: PIL Image to convert
            output_format: Format for the output (JPEG, PNG, etc.)
            quality: Quality for JPEG output (1-100)
            
        Returns:
            Image data as bytes
        """
        try:
            output_buffer = BytesIO()
            image.save(
                output_buffer,
                format=output_format,
                quality=quality,
                optimize=True
            )
            return output_buffer.getvalue()
        except Exception as e:
            raise ImageProcessingError(f"Cannot convert image to bytes: {e}")
    
    @staticmethod
    def create_roi_from_center(
        center_x: float,
        center_y: float,
        width: float,
        height: float
    ) -> RegionOfInterest:
        """
        Create ROI from center coordinates.
        
        Args:
            center_x: X coordinate of center (0.0-1.0)
            center_y: Y coordinate of center (0.0-1.0)
            width: Width of region (0.0-1.0)
            height: Height of region (0.0-1.0)
            
        Returns:
            RegionOfInterest instance
        """
        x = center_x - (width / 2)
        y = center_y - (height / 2)
        
        # Ensure coordinates stay within bounds
        x = max(0.0, min(x, 1.0 - width))
        y = max(0.0, min(y, 1.0 - height))
        
        return RegionOfInterest(x=x, y=y, width=width, height=height)
    
    @staticmethod
    def get_default_roi() -> RegionOfInterest:
        """
        Get default ROI for "slightly below center" region.
        Example: x=0.1, y=0.6, width=0.8, height=0.3
        
        Returns:
            Default RegionOfInterest
        """
        return RegionOfInterest(x=0.1, y=0.6, width=0.8, height=0.3)
