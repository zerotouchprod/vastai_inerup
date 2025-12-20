import logging
import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import List, Optional, Union
import torch

# Try importing PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

logger = logging.getLogger(__name__)

class MaskGeneratorService:
    """
    Generates text masks using aggressive OCR settings.
    Optimized for CPU usage and hard-to-read subtitles.
    """

    def __init__(self, 
                 lang: str = 'ru', 
                 mask_dilation: int = 15,
                 use_gpu_for_ocr: bool = False,
                 confidence_threshold: float = 0.1): 
        
        self.lang = lang
        self.mask_dilation = mask_dilation
        # FORCE CPU for stability since the environment has CUDA errors
        self.use_gpu = False 
        self.confidence_threshold = 0.01 # Ultra-low threshold
        
        if not PADDLE_AVAILABLE:
            logger.warning("PaddleOCR not installed. Text detection will be disabled.")
            self.ocr = None
            return

        logger.info(f"Initializing PaddleOCR (Aggressive Mode)... Lang={self.lang}, GPU={self.use_gpu}")
        
        # AGGRESSIVE PADDLE CONFIGURATION (using parameter names from paddle_wrapper)
        try:
            self.ocr = PaddleOCR(
                lang=self.lang,
                use_textline_orientation=True,
                det_model_dir=None,   # Use default mobile model (deprecated but still works)
                rec_model_dir=None,   # Use default mobile model (deprecated)
                cls_model_dir=None,   # No classification model (deprecated)
                
                # --- DETECTION TUNING (The "Berserk" Mode) ---
                text_det_thresh=0.1,          # Lower binarization threshold (default 0.3)
                text_det_box_thresh=0.1,      # Lower box threshold (default 0.6)
                text_det_unclip_ratio=2.5,    # Expand detection boxes (default 1.5)
                text_det_limit_side_len=960,  # Increase side length limit
                text_det_limit_type='max',    # Limit by max side
                
                # --- RECOGNITION TUNING ---
                text_rec_score_thresh=0.01,   # Keep recognition result even if confidence low (default 0.5)
            )
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            self.ocr = None

    def _enhance_image_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """
        Applies 'Contrast Shower' to make text pop out.
        Grayscale -> CLAHE -> BGR
        """
        if image is None:
            return image
            
        # 1. Convert to Grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
            
        # 2. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # clipLimit=4.0 makes it very aggressive (high contrast)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        
        # 3. Convert back to BGR (Paddle expects 3 channels)
        return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    def generate_masks(self, input_dir: Path, output_dir: Path) -> Path:
        """
        Process a directory of images and generate masks.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        images = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        logger.info(f"Generating masks for {len(images)} frames in {input_dir}")

        for img_path in images:
            # 1. Load
            frame = cv2.imread(str(img_path))
            if frame is None:
                continue

            # 2. Generate Mask (Using Hybrid Detection)
            masks = self._process_batch_with_hybrid_detection([frame])
            
            # 3. Save
            mask_name = img_path.name
            # Ensure png extension for mask (lossless)
            if mask_name.endswith('.jpg'):
                mask_name = mask_name[:-4] + '.png'
            
            if masks:
                cv2.imwrite(str(output_dir / mask_name), masks[0])
            else:
                # Fallback: empty black mask
                h, w = frame.shape[:2]
                empty = np.zeros((h, w), dtype=np.uint8)
                cv2.imwrite(str(output_dir / mask_name), empty)

        return output_dir

    def cleanup_temp_dir(self, dir_path: Path):
        if dir_path.exists():
            shutil.rmtree(dir_path)

    def _process_batch_with_hybrid_detection(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Process a batch of frames to generate text masks using OCR.
        Includes Pre-processing (Enhancement).
        """
        if self.ocr is None:
            return [np.zeros((f.shape[0], f.shape[1]), dtype=np.uint8) for f in frames]

        masks = []
        for frame in frames:
            h, w = frame.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            
            # --- STEP 1: ENHANCE IMAGE (The Fix) ---
            # Explicitly enhance the image before giving it to OCR
            ocr_input = self._enhance_image_for_ocr(frame)
            
            try:
                # --- STEP 2: DETECT ---
                # ocr_input is now high-contrast
                result = self.ocr.ocr(ocr_input, cls=True, rec=True)
                
                # --- STEP 3: DRAW MASK ---
                if result and result[0]:
                    for line in result[0]:
                        # Paddle format: [[ [x1,y1],[x2,y2],[x3,y3],[x4,y4] ], (text, confidence)]
                        coords = line[0]
                        points = np.array(coords, dtype=np.int32)
                        
                        # Fill the detected text area with white
                        cv2.fillPoly(mask, [points], 255)
                
                # --- STEP 4: DILATE (Expand mask to cover artifacts) ---
                if self.mask_dilation > 0:
                    kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
                    mask = cv2.dilate(mask, kernel, iterations=1)
                    
            except Exception as e:
                logger.error(f"OCR failed on frame: {e}")
                
            masks.append(mask)
            
        return masks
