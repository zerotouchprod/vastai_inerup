"""
Main hybrid mask service that combines OCR and CV detectors.
"""

import logging
import os
from pathlib import Path
from typing import List, Tuple, Union, Optional
import numpy as np
import cv2

from src.services.masking.interfaces import TextDetector
from src.services.masking.detectors.ocr_engine import OCREngine
from src.services.masking.detectors.cv_engine import CVEngine

logger = logging.getLogger(__name__)


class HybridMaskService:
    """
    Ultimate Hybrid MaskService that combines AI (PaddleOCR) and
    Computer Vision (morphological operations) for robust text detection.
    
    Features:
    - Version-agnostic OCR with auto-healing initialization.
    - Morphological text hunter for colored/outlined text.
    - Graceful degradation: works even if OCR fails.
    - Batch processing support for video frames.
    """
    
    def __init__(self,
                 lang: str = 'en',
                 mask_dilation: int = 15,
                 use_gpu_for_ocr: bool = False,
                 confidence_threshold: float = 0.1):
        """
        Initialize hybrid mask service.
        
        Args:
            lang: Language for OCR (default: 'en')
            mask_dilation: Dilation radius for masks (default: 15)
            use_gpu_for_ocr: Use GPU for OCR if available (default: False)
            confidence_threshold: Minimum confidence for text detection (default: 0.1)
        """
        self.lang = lang
        self.mask_dilation = mask_dilation
        self.use_gpu_for_ocr = use_gpu_for_ocr
        self.confidence_threshold = confidence_threshold
        
        logger.info(f"Initializing HybridMaskService (lang={lang}, dilation={mask_dilation}, "
                   f"GPU={use_gpu_for_ocr}, confidence={confidence_threshold})")
        
        # Initialize detectors
        self.ocr_engine = OCREngine(
            lang=lang,
            use_gpu=use_gpu_for_ocr,
            confidence_threshold=confidence_threshold
        )
        
        self.cv_engine = CVEngine(mask_dilation=mask_dilation)
        
        # Log detector status
        if self.ocr_engine.is_available():
            logger.info("OCR Engine ready")
        else:
            logger.warning("OCR Engine not available - will rely on CV Engine only")
        
        logger.info("CV Engine ready")
    
    def process_image(self, image_input: Union[str, np.ndarray]) -> Tuple[np.ndarray, List[str]]:
        """
        Process a single image and return masked image with detected text.
        
        Args:
            image_input: Either a file path (str) or numpy array (BGR image).
            
        Returns:
            Tuple of (masked_image, detected_text_list).
            The masked image has detected text regions blacked out.
            The text list is a placeholder for backward compatibility.
        """
        try:
            # Load image
            if isinstance(image_input, str):
                if not os.path.exists(image_input):
                    raise FileNotFoundError(f"Image not found: {image_input}")
                img = cv2.imread(image_input)
            else:
                img = image_input
            
            if img is None:
                return image_input if isinstance(image_input, np.ndarray) else cv2.imread(image_input), []
            
            h, w = img.shape[:2]
            
            # Get masks from both detectors
            mask_ocr = self.ocr_engine.detect(img)
            mask_cv = self.cv_engine.detect(img)
            
            # Combine masks
            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)
            
            # Count detected regions for logging
            ocr_regions = np.count_nonzero(mask_ocr) // 255  # approximate
            cv_regions = np.count_nonzero(mask_cv) // 255
            
            # Apply mask to image (black out detected regions)
            masked_img = img.copy()
            masked_img[final_mask > 0] = (0, 0, 0)
            
            logger.info(f"Mask generation: OCR found {ocr_regions} regions, "
                       f"CV found {cv_regions} regions. Combined.")
            
            # Return placeholder text list for backward compatibility
            return masked_img, ["<hybrid_masked>"]
            
        except Exception as e:
            logger.error(f"Image processing failed: {e}", exc_info=True)
            # Return original image on error
            if isinstance(image_input, np.ndarray):
                return image_input, []
            else:
                img = cv2.imread(image_input)
                return img if img is not None else np.zeros((100, 100, 3), dtype=np.uint8), []
    
    def generate_masks(self,
                       input_dir: Union[str, Path],
                       output_dir: Union[str, Path],
                       batch_size: Optional[int] = None) -> Path:
        """
        Generate masks for all frames in input directory.
        
        Args:
            input_dir: Directory containing input frames (PNG/JPG).
            output_dir: Directory where masks will be saved.
            batch_size: Optional batch size for processing (not used in current implementation).
            
        Returns:
            Path to the output directory with masks.
        """
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_path}")
        
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Collect frame paths
        frame_paths = sorted(list(input_path.glob("*.png")) + list(input_path.glob("*.jpg")))
        if not frame_paths:
            logger.warning(f"No frames found in {input_path}")
            return output_path
        
        logger.info(f"Generating masks for {len(frame_paths)} frames from {input_path}")
        
        # Process frames
        for idx, frame_path in enumerate(frame_paths):
            try:
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    logger.warning(f"Failed to load frame: {frame_path}")
                    continue
                
                # Get masks from both detectors
                mask_ocr = self.ocr_engine.detect(frame)
                mask_cv = self.cv_engine.detect(frame)
                
                # Combine masks
                final_mask = cv2.bitwise_or(mask_ocr, mask_cv)
                
                # Save mask
                mask_filename = f"mask_{idx:05d}.png"
                mask_path = output_path / mask_filename
                cv2.imwrite(str(mask_path), final_mask)
                
                # Log progress every 10 frames
                if (idx + 1) % 10 == 0 or (idx + 1) == len(frame_paths):
                    logger.info(f"Processed {idx + 1}/{len(frame_paths)} frames")
                    
            except Exception as e:
                logger.error(f"Failed to process frame {frame_path}: {e}")
                continue
        
        logger.info(f"Saved {len(frame_paths)} masks to {output_path}")
        return output_path
    
    def cleanup_temp_dir(self, dir_path: Union[str, Path]):
        """
        Remove temporary directory created during mask generation.
        
        Args:
            dir_path: Path to directory to remove.
        """
        import shutil
        dir_path = Path(dir_path)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            logger.info(f"Cleaned up temporary directory: {dir_path}")
        else:
            logger.warning(f"Directory does not exist: {dir_path}")
    
    def is_available(self) -> bool:
        """
        Check if the service is available (at least one detector works).
        
        Returns:
            True if at least one detector is available.
        """
        return self.ocr_engine.is_available() or self.cv_engine.is_available()
