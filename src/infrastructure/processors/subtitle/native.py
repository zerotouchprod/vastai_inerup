"""
SubtitleRemoverNative - Facade class for subtitle removal pipeline.
Orchestrates OCR detection, mask generation, temporal filtering, and inpainting.
"""

import logging
import gc
import shutil
from typing import Optional, List
from pathlib import Path
import numpy as np
import cv2
import psutil

from src.core.config import AppConfig, get_config
from src.infrastructure.detection.components.ocr_engine import OcrEngine
from src.infrastructure.detection.components.mask_generator import MaskGenerator
from src.infrastructure.detection.components.inpainter import Inpainter
from src.infrastructure.detection.components.temporal import TemporalFilter
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
        
        # Collect masks and images for temporal processing (we need a buffer)
        # Note: Ideally temporal filter should work on streams, but for simplicity 
        # we often process in larger chunks or 2 passes. 
        # Here we follow the logic: 1. Generate ALL masks, 2. Filter, 3. Inpaint
        # This uses more RAM but guarantees temporal consistency.
        
        # If RAM is an issue, we should switch to a sliding window buffer approach.
        # For now, let's keep the 2-pass approach but optimize data storage.
        
        all_masks = []
        all_frame_paths = []
        # We don't store full images in RAM for the whole video anymore to prevent OOM
        
        # First pass: detect text and create masks
        logger.info("First pass: Detecting text and creating masks...")
        
        for batch_frames in self._chunk(frames, batch_size):
            logger.info(f"Processing batch {processed // batch_size + 1}/{(total + batch_size - 1)//batch_size} "
                        f"({len(batch_frames)} frames)...")
            
            for frame_path in batch_frames:
                try:
                    img = cv2.imread(str(frame_path))
                    if img is None:
                        logger.warning(f"Could not read image: {frame_path}")
                        # Append empty mask placeholder
                        all_masks.append(None) 
                        all_frame_paths.append(frame_path)
                        continue
                    
                    # Preprocess & Detect
                    preprocessed_img = self.mask_gen.preprocess_for_ocr(img)
                    ocr_results = self.ocr.detect_text(preprocessed_img)
                    
                    # Generate mask
                    mask = self.mask_gen.generate_mask(img, ocr_results, self.config.ROI)
                    
                    all_masks.append(mask)
                    all_frame_paths.append(frame_path)
                    processed += 1
                    
                    # Show progress
                    if processed % 5 == 0 or processed == total:
                        process = psutil.Process()
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        logger.info(f"Processed {processed}/{total} frames for mask detection... Memory: {memory_mb:.1f} MB")
                        
                except Exception as e:
                    logger.error(f"Failed to process frame {frame_path} for mask detection: {e}")
                    all_masks.append(None)
                    all_frame_paths.append(frame_path)
            
            # Force GC between batches
            gc.collect()
            
            # Check memory
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"Batch completed. Memory usage: {memory_mb:.1f} MB")
            if memory_mb > 4000:
                logger.warning(f"High memory usage detected: {memory_mb:.1f} MB. Consider reducing batch size.")

        # Fill None masks with zeros based on first valid mask
        valid_shape = next((m.shape for m in all_masks if m is not None), (100, 100))
        all_masks = [m if m is not None else np.zeros(valid_shape, dtype=np.uint8) for m in all_masks]

        # Apply temporal filtering
        logger.info("Applying temporal filtering to masks...")
        filtered_masks = self.temporal.process_batch(all_masks)
        
        # Release raw masks to free memory
        del all_masks
        gc.collect()
        
        # Second pass: Inpainting (Load image -> Inpaint -> Save -> Release)
        logger.info("Second pass: Applying inpainting...")
        processed = 0
        
        for i, (frame_path, mask) in enumerate(zip(all_frame_paths, filtered_masks)):
            try:
                output_path = output_dir / frame_path.name
                
                # Skip inpainting if mask is empty
                if np.max(mask) == 0:
                    # Just copy original (faster than re-encoding)
                    shutil.copy(frame_path, output_path)
                    processed += 1
                    continue
                
                # Load image again (fresh from disk)
                img = cv2.imread(str(frame_path))
                if img is None: 
                    logger.warning(f"Could not read image for inpainting: {frame_path}")
                    shutil.copy(frame_path, output_path)
                    continue

                # Inpaint
                result_img = self.inpainter.inpaint(img, mask)
                
                # Save
                cv2.imwrite(str(output_path), result_img)
                processed += 1
                
                if processed % 5 == 0 or processed == total:
                    logger.info(f"Processed {processed}/{total} frames for inpainting...")
                    
            except Exception as e:
                logger.error(f"Failed to inpaint frame {frame_path}: {e}")
                # Fallback copy
                shutil.copy(frame_path, output_path)

        logger.info(f"Completed subtitle removal on {total} frames.")
    
    def process_single_frame(self, input_path: Path, output_path: Path) -> None:
        """Process single frame for subtitle removal."""
        img = cv2.imread(str(input_path))
        if img is None:
            raise ValueError(f"Could not read image: {input_path}")
        
        # Pipeline
        prep = self.mask_gen.preprocess_for_ocr(img)
        res = self.ocr.detect_text(prep)
        if not res:
            cv2.imwrite(str(output_path), img)
            return
            
        mask = self.mask_gen.generate_mask(img, res, self.config.ROI)
        if np.max(mask) == 0:
            cv2.imwrite(str(output_path), img)
            return
            
        final = self.inpainter.inpaint(img, mask)
        cv2.imwrite(str(output_path), final)
    
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
    
    def cleanup(self):
        """
        Clean up resources from all components.
        """
        self.ocr.cleanup()
        logger.info("SubtitleRemoverNative cleanup completed")
