"""
SubtitleRemoverNative - Facade class for subtitle removal pipeline.
Orchestrates OCR detection, mask generation, temporal filtering, and inpainting.
"""

import logging
import gc
from typing import Optional, List
from pathlib import Path
import numpy as np
import cv2
import psutil

from src.core.config import AppConfig, get_config
from src.infrastructure.detection.components import (
    OcrEngine, MaskGenerator, Inpainter, TemporalFilter
)
from src.infrastructure.utils.gpu_utils import require_gpu

# Remove global side effects - logging suppression is now handled by OcrEngine
logger = logging.getLogger(__name__)


class SubtitleRemoverNative:
    """
    Facade class that orchestrates the subtitle removal pipeline.
    
    Responsibilities:
    1. Loading AppConfig and initializing components
    2. Iterating through files and managing batch processing
    3. Coordinating between OCR, mask generation, temporal filtering, and inpainting
    """
    
    def __init__(self, config: Optional[AppConfig] = None):
        """
        Initialize subtitle remover with configuration.
        
        Args:
            config: AppConfig instance. If None, loads default config.
        """
        # Load configuration
        self.config: AppConfig = config or get_config()
        
        # CRITICAL: Subtitle removal requires GPU for OCR and inpainting
        require_gpu("subtitle removal (native)")
        
        # Initialize components
        self.ocr = OcrEngine(self.config)
        self.mask_gen = MaskGenerator(self.config)
        self.inpainter = Inpainter(self.config)
        self.temporal = TemporalFilter(window_size=2)
        
        logger.info(f"SubtitleRemoverNative initialized with components")
    
    def process_frames(self, input_dir: Path, output_dir: Path) -> None:
        """
        Process all images in input_dir and save to output_dir.
        Optimized for memory usage with batch processing.
        
        Args:
            input_dir: Directory containing input frames
            output_dir: Directory for output frames
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get list of files (png/jpg)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        total = len(frames)
        
        if total == 0:
            logger.warning(f"No frames found in {input_dir}")
            return
        
        logger.info(f"Starting subtitle removal on {total} frames...")
        
        # Process in smaller batches to reduce memory pressure
        batch_size = 4
        processed = 0
        
        # Collect masks and images for temporal processing
        all_masks = []
        all_frame_paths = []
        all_images = []
        
        # First pass: detect text and create masks for all frames
        logger.info("First pass: Detecting text and creating masks...")
        
        for batch_frames in self._chunk(frames, batch_size):
            logger.info(f"Processing batch {processed // batch_size + 1}/{(total + batch_size - 1)//batch_size} "
                       f"({len(batch_frames)} frames)...")
            
            for frame_path in batch_frames:
                try:
                    # Load image
                    img = cv2.imread(str(frame_path))
                    if img is None:
                        logger.warning(f"Could not read image: {frame_path}")
                        # Create empty mask
                        h, w = 100, 100  # Default size
                        if all_images:
                            h, w = all_images[0].shape[:2]
                        mask = np.zeros((h, w), dtype=np.uint8)
                        all_masks.append(mask)
                        all_frame_paths.append(frame_path)
                        all_images.append(np.zeros((h, w, 3), dtype=np.uint8))
                        continue
                    
                    # Store image for later processing
                    all_images.append(img)
                    all_frame_paths.append(frame_path)
                    
                    # Preprocess image for better OCR detection
                    preprocessed_img = self.mask_gen.preprocess_for_ocr(img)
                    
                    # Detect text with OCR engine
                    ocr_results = self.ocr.detect_text(preprocessed_img)
                    
                    # Generate mask using mask generator
                    mask = self.mask_gen.generate_mask(img, ocr_results, self.config.ROI)
                    all_masks.append(mask)
                    processed += 1
                    
                    # Show progress
                    if processed % 5 == 0 or processed == total:
                        process = psutil.Process()
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        logger.info(f"Processed {processed}/{total} frames for mask detection... Memory: {memory_mb:.1f} MB")
                        
                except Exception as e:
                    logger.error(f"Failed to process frame {frame_path} for mask detection: {e}")
                    # Create empty mask
                    h, w = 100, 100
                    if all_images:
                        h, w = all_images[0].shape[:2]
                    mask = np.zeros((h, w), dtype=np.uint8)
                    all_masks.append(mask)
                    all_frame_paths.append(frame_path)
                    if len(all_images) < len(all_masks):
                        all_images.append(np.zeros((h, w, 3), dtype=np.uint8))
                    processed += 1
            
            # Force garbage collection between batches
            gc.collect()
            
            # Check memory usage between batches
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"Batch completed. Memory usage: {memory_mb:.1f} MB")
            
            if memory_mb > 4000:  # 4GB threshold
                logger.warning(f"High memory usage detected: {memory_mb:.1f} MB. Consider reducing batch size.")
        
        # Apply temporal filtering (includes smearing and validation)
        logger.info("Applying temporal filtering to masks...")
        filtered_masks = self.temporal.process_batch(all_masks)
        
        # Second pass: apply inpainting with temporally filtered masks
        logger.info("Second pass: Applying inpainting...")
        processed = 0
        
        for i, (frame_path, img, mask) in enumerate(zip(all_frame_paths, all_images, filtered_masks)):
            try:
                output_path = output_dir / frame_path.name
                
                # Skip if no text detected (empty mask)
                if np.max(mask) == 0:
                    cv2.imwrite(str(output_path), img)
                    processed += 1
                    continue
                
                # Inpaint using inpainter component
                result_img = self.inpainter.inpaint(img, mask)
                
                # Save result
                cv2.imwrite(str(output_path), result_img)
                processed += 1
                
                # Show progress
                if processed % 5 == 0 or processed == total:
                    logger.info(f"Processed {processed}/{total} frames for inpainting...")
                    
            except Exception as e:
                logger.error(f"Failed to process frame {frame_path} for inpainting: {e}")
                # Save original as fallback
                cv2.imwrite(str(output_dir / frame_path.name), img)
                processed += 1
        
        logger.info(f"Completed subtitle removal on {total} frames with temporal filtering.")
    
    def _chunk(self, items: List, size: int):
        """
        Split list into chunks of specified size.
        
        Args:
            items: List to split
            size: Chunk size
            
        Yields:
            Chunks of items
        """
        for i in range(0, len(items), size):
            yield items[i:i + size]
    
    def process_single_frame(self, input_path: Path, output_path: Path) -> None:
        """
        Process single frame for subtitle removal.
        
        Args:
            input_path: Path to input image
            output_path: Path to output image
        """
        # Load image
        img = cv2.imread(str(input_path))
        if img is None:
            raise ValueError(f"Could not read image: {input_path}")
        
        # Preprocess for OCR
        preprocessed_img = self.mask_gen.preprocess_for_ocr(img)
        
        # Detect text
        ocr_results = self.ocr.detect_text(preprocessed_img)
        
        # If no text detected, save original
        if not ocr_results:
            cv2.imwrite(str(output_path), img)
            return
        
        # Generate mask
        mask = self.mask_gen.generate_mask(img, ocr_results, self.config.ROI)
        
        # If empty mask, save original
        if np.max(mask) == 0:
            cv2.imwrite(str(output_path), img)
            return
        
        # Inpaint
        result_img = self.inpainter.inpaint(img, mask)
        
        # Save result
        cv2.imwrite(str(output_path), result_img)
    
    def cleanup(self):
        """
        Clean up resources from all components.
        """
        self.ocr.cleanup()
        logger.info("SubtitleRemoverNative cleanup completed")
