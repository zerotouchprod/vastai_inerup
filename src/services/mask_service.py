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
            
            # Get all frame files
            frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
            if not frames:
                raise ProcessingError(f"No frames found in directory: {input_dir}")
            
            # Process in smaller batches to manage memory but maintain temporal context
            # We need to process all frames to apply temporal smearing
            # Use a larger batch size for efficiency but process sequentially
            effective_batch_size = min(batch_size, 16)  # Limit batch size
            
            all_masks = []
            all_frame_paths = []
            
            # Process frames in batches
            for i in range(0, len(frames), effective_batch_size):
                batch_frames = frames[i:i + effective_batch_size]
                
                # Load images
                images = []
                valid_paths = []
                
                for frame_path in batch_frames:
                    img = cv2.imread(str(frame_path))
                    if img is not None:
                        images.append(img)
                        valid_paths.append(frame_path)
                
                if not images:
                    continue
                
                # Preprocess images for better OCR detection
                preprocessed_images = [self._preprocess_for_ocr(img) for img in images]
                
                # Generate masks for this batch
                batch_masks = self.ocr_wrapper.process_batch(preprocessed_images, self.confidence_threshold)
                
                # Store masks and paths for temporal smearing
                all_masks.extend(batch_masks)
                all_frame_paths.extend(valid_paths)
                
                # Log progress
                processed = min(i + effective_batch_size, len(frames))
                if (i + effective_batch_size) % (effective_batch_size * 5) == 0 or processed == len(frames):
                    logger.info(f"Processed {processed}/{len(frames)} frames for mask generation")
            
            if not all_masks:
                raise ProcessingError("No masks generated")
            
            # Apply temporal smearing (rolling window of ±2 frames)
            window_size = 2  # Look 2 frames back and 2 frames forward
            smeared_masks = []
            
            for i in range(len(all_masks)):
                # Get indices for the window
                start_idx = max(0, i - window_size)
                end_idx = min(len(all_masks), i + window_size + 1)
                
                # Combine masks in the window using logical OR (max)
                window_masks = all_masks[start_idx:end_idx]
                if window_masks:
                    # Use logical OR to combine masks (equivalent to max for binary masks)
                    combined_mask = window_masks[0].copy()
                    for mask in window_masks[1:]:
                        combined_mask = cv2.bitwise_or(combined_mask, mask)
                    smeared_masks.append(combined_mask)
                else:
                    smeared_masks.append(all_masks[i])
            
            # Apply dilation and morphological closing, then save masks
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
                closing_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            else:
                kernel = None
                closing_kernel = None
            
            for frame_path, mask in zip(all_frame_paths, smeared_masks):
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
            
            # Count generated masks
            mask_files = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
            logger.info(f"Masks generated successfully with temporal smearing: {output_dir} ({len(mask_files)} masks)")
            return output_dir
            
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
    
    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
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
            
            # Preprocess images for better OCR detection of colored/fading text
            preprocessed_images = [self._preprocess_for_ocr(img) for img in images]
            
            # Generate masks using preprocessed images
            masks = self.ocr_wrapper.process_batch(preprocessed_images, self.confidence_threshold)
            
            # Apply temporal smearing (rolling window of ±2 frames)
            window_size = 2  # Look 2 frames back and 2 frames forward
            smeared_masks = []
            
            for i in range(len(masks)):
                # Get indices for the window
                start_idx = max(0, i - window_size)
                end_idx = min(len(masks), i + window_size + 1)
                
                # Combine masks in the window using logical OR (max)
                window_masks = masks[start_idx:end_idx]
                if window_masks:
                    # Use logical OR to combine masks (equivalent to max for binary masks)
                    combined_mask = window_masks[0].copy()
                    for mask in window_masks[1:]:
                        combined_mask = cv2.bitwise_or(combined_mask, mask)
                    smeared_masks.append(combined_mask)
                else:
                    smeared_masks.append(masks[i])
            
            # Apply dilation and morphological closing
            mask_paths = []
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
                closing_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            else:
                kernel = None
                closing_kernel = None
            
            for frame_path, mask in zip(valid_paths, smeared_masks):
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
            
            logger.info(f"Generated {len(mask_paths)} masks with temporal smearing (window_size={window_size})")
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
