"""
Mask generation service for subtitle removal.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from src.core.config import get_config
from src.core.exceptions import ProcessingError
from src.infrastructure.ocr.paddle_wrapper import ThreadSafeOCR

logger = logging.getLogger(__name__)


class MaskGeneratorService:
    """Service for generating subtitle masks."""
    
    def __init__(self, 
                 lang: Optional[str] = None,
                 mask_dilation: Optional[int] = None,
                 use_gpu_for_ocr: Optional[bool] = None,
                 confidence_threshold: Optional[float] = None):
        """
        Initialize mask generator service.
        
        Args:
            lang: Language for OCR (default from config)
            mask_dilation: Mask dilation radius (default from config)
            use_gpu_for_ocr: Use GPU for OCR (default from config)
            confidence_threshold: Confidence threshold for text detection (default from config)
        """
        config = get_config()
        
        self.lang = lang or config.OCR_LANG
        self.mask_dilation = mask_dilation or config.MASK_DILATION
        self.use_gpu_for_ocr = use_gpu_for_ocr if use_gpu_for_ocr is not None else config.USE_GPU_FOR_OCR
        self.confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # Initialize OCR wrapper
        self.ocr_wrapper = ThreadSafeOCR(
            lang=self.lang,
            use_gpu_for_ocr=self.use_gpu_for_ocr,
            use_angle_cls=False
        )
        
        logger.info(f"MaskGeneratorService initialized (lang={self.lang}, "
                   f"dilation={self.mask_dilation}, confidence={self.confidence_threshold})")
    
    def generate_masks(self, input_dir: Path, output_dir: Path, batch_size: int = 8) -> Path:
        """
        Generate masks for all frames in directory.
        
        Args:
            input_dir: Directory with input frames
            output_dir: Directory to save masks
            batch_size: Batch size for processing
            
        Returns:
            Path to directory with masks
            
        Raises:
            ProcessingError: If mask generation fails
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Starting mask generation for {input_dir} -> {output_dir}")
            logger.info(f"Parameters: lang={self.lang}, dilation={self.mask_dilation}, "
                       f"confidence={self.confidence_threshold}, batch_size={batch_size}")
            
            # Generate masks using OCR wrapper with minimal batch size
            # Use batch_size=1 for absolute minimum memory usage
            minimal_batch_size = min(batch_size, 2)  # Max 2 frames at a time
            mask_dir = self.ocr_wrapper.create_masks_for_directory(
                input_dir=input_dir,
                output_dir=output_dir,
                batch_size=minimal_batch_size,
                confidence_threshold=self.confidence_threshold
            )
            
            # Apply dilation if needed
            if self.mask_dilation > 0:
                self._apply_dilation(mask_dir)
            
            # Count generated masks
            mask_files = list(mask_dir.glob("*.png")) + list(mask_dir.glob("*.jpg"))
            logger.info(f"Masks generated successfully: {mask_dir} ({len(mask_files)} masks)")
            return mask_dir
            
        except Exception as e:
            logger.error(f"Failed to generate masks: {e}")
            raise ProcessingError(f"Failed to generate masks: {e}")
    
    def _apply_dilation(self, mask_dir: Path) -> None:
        """Apply dilation and morphological closing to all masks in directory."""
        logger.info(f"Applying dilation (radius={self.mask_dilation}) and morphological closing to masks...")
        
        # Get all mask files
        mask_files = sorted(list(mask_dir.glob("*.png")) + list(mask_dir.glob("*.jpg")))
        
        if not mask_files:
            logger.warning(f"No mask files found in {mask_dir}")
            return
        
        # Create dilation kernel
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
        # Kernel for morphological closing (merge individual letters into solid blocks)
        closing_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        
        # Process each mask
        for mask_file in mask_files:
            try:
                mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
                if mask is None:
                    continue
                
                # Apply morphological closing to merge individual letters
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, closing_kernel)
                # Apply dilation to expand the mask
                dilated_mask = cv2.dilate(mask, kernel, iterations=1)
                # Additional dilation to ensure coverage
                dilated_mask = cv2.dilate(dilated_mask, kernel, iterations=2)
                
                # Additional smoothing for large dilation
                if self.mask_dilation >= 8:
                    dilated_mask = cv2.GaussianBlur(dilated_mask, (5, 5), 0)
                
                # Save back
                cv2.imwrite(str(mask_file), dilated_mask)
                
            except Exception as e:
                logger.warning(f"Failed to process mask {mask_file}: {e}")
        
        logger.info(f"Dilation and morphological closing applied to {len(mask_files)} masks")
    
    def generate_masks_for_frames(self, frame_paths: list[Path], output_dir: Path) -> list[Path]:
        """
        Generate masks for specific frame paths.
        
        Args:
            frame_paths: List of frame paths
            output_dir: Directory to save masks
            
        Returns:
            List of mask paths (same order as input)
            
        Raises:
            ProcessingError: If mask generation fails
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Load images
            images = []
            valid_paths = []
            
            for frame_path in frame_paths:
                img = cv2.imread(str(frame_path))
                if img is not None:
                    images.append(img)
                    valid_paths.append(frame_path)
            
            if not images:
                raise ProcessingError("No valid images found")
            
            # Generate masks
            masks = self.ocr_wrapper.process_batch(images, self.confidence_threshold)
            
            # Apply dilation and morphological closing
            mask_paths = []
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
                closing_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            else:
                kernel = None
                closing_kernel = None
            
            for frame_path, mask in zip(valid_paths, masks):
                # Apply morphological closing to merge individual letters
                if closing_kernel is not None:
                    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, closing_kernel)
                # Apply dilation if needed
                if kernel is not None:
                    mask = cv2.dilate(mask, kernel, iterations=1)
                    mask = cv2.dilate(mask, kernel, iterations=2)  # Additional dilation for coverage
                    if self.mask_dilation >= 8:
                        mask = cv2.GaussianBlur(mask, (5, 5), 0)
                
                # Save mask
                mask_path = output_dir / frame_path.name
                cv2.imwrite(str(mask_path), mask)
                mask_paths.append(mask_path)
            
            logger.info(f"Generated {len(mask_paths)} masks")
            return mask_paths
            
        except Exception as e:
            raise ProcessingError(f"Failed to generate masks for frames: {e}")
    
    def cleanup_temp_dir(self, temp_dir: Path) -> None:
        """Clean up temporary directory."""
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")
