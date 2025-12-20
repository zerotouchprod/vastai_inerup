import logging
import shutil
import cv2
import numpy as np
import re
import os
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

# Try importing PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False

logger = logging.getLogger(__name__)


class MaskGeneratorService:
    """
    Generates text masks using Triple-Pass OCR (Normal, Inverted, Binary) + Upscaling.
    Optimized for CPU usage and hard-to-read subtitles.
    """

    def __init__(self,
                 lang: str = 'ru',
                 mask_dilation: int = 15,
                 use_gpu_for_ocr: bool = False,
                 confidence_threshold: float = 0.1):

        self.lang = lang
        self.mask_dilation = mask_dilation
        self.use_gpu = use_gpu_for_ocr  # Use GPU if requested
        self.confidence_threshold = confidence_threshold

        if not PADDLE_AVAILABLE:
            logger.warning("PaddleOCR not installed. Text detection will be disabled.")
            self.ocr = None
            return

        logger.info(f"Initializing PaddleOCR with auto-healing configuration... Lang={self.lang}")

        # Ideal configuration (wishlist)
        ideal_config = {
            "use_angle_cls": True,
            "lang": self.lang,
            "use_gpu": self.use_gpu,
            "show_log": False,
            "enable_mkldnn": True,
            "det_db_thresh": 0.3,
            "det_db_box_thresh": 0.6,
            "det_db_unclip_ratio": 1.5,
            "rec_thresh": 0.6,
        }

        # Robust initialization
        self.ocr = self._init_ocr_robust(ideal_config)

    def _init_ocr_robust(self, params: Dict[str, Any]):
        """
        Attempts to initialize PaddleOCR. Catches both standard TypeErrors and 
        library-specific Exceptions regarding unknown arguments, strips them, 
        and retries.
        """
        attempts = 0
        max_attempts = len(params) + 2

        current_params = params.copy()

        # Regex patterns to catch various "unknown argument" error formats
        error_patterns = [
            r"unexpected keyword argument ['\"]([^'\"]+)['\"]",  # Python standard
            r"Unknown argument:?\s+([A-Za-z0-9_]+)",            # Paddle specific (Your Error)
            r"got an unexpected keyword argument ['\"]([^'\"]+)['\"]"
        ]

        while attempts < max_attempts:
            try:
                logger.debug(f"Attempting PaddleOCR init with keys: {list(current_params.keys())}")
                # Try to initialize
                ocr_instance = PaddleOCR(**current_params)
                
                logger.info(f"PaddleOCR initialized successfully. Active config: {current_params}")
                return ocr_instance

            except Exception as e:
                error_msg = str(e)
                logger.warning(f"PaddleOCR init failed with error: {error_msg}. Analyzing for bad params...")
                
                bad_arg = None
                
                # Check all regex patterns
                for pattern in error_patterns:
                    match = re.search(pattern, error_msg)
                    if match:
                        bad_arg = match.group(1)
                        break
                
                if bad_arg:
                    logger.warning(f"PaddleOCR rejected parameter '{bad_arg}'. Removing and retrying...")
                    if bad_arg in current_params:
                        del current_params[bad_arg]
                    else:
                        logger.critical(f"Detected bad arg '{bad_arg}' but it's not in params. Aborting loop.")
                        raise e
                else:
                    # If we can't identify the bad argument, we must fail to avoid infinite loops
                    logger.critical(f"Could not identify the problematic argument in error: '{error_msg}'. Aborting.")
                    raise e
            
            attempts += 1
        
        raise RuntimeError("PaddleOCR failed to initialize after exhausting parameter stripping attempts.")

    def _enhance_variants(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Generates 3 variants of the image to force OCR detection:
        1. Enhanced (CLAHE)
        2. Inverted (Negative)
        3. Binary Threshold (Pure B&W)
        """
        if image is None:
            return []

        # 0. UPSCALE (Critical for small text)
        # Resize 2x to make text clearer
        h, w = image.shape[:2]
        upscaled = cv2.resize(image, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # Convert to Grayscale
        if len(upscaled.shape) == 3:
            gray = cv2.cvtColor(upscaled, cv2.COLOR_BGR2GRAY)
        else:
            gray = upscaled

        variants = []

        # Variant 1: CLAHE (Contrast)
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        variants.append(cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR))

        # Variant 2: Inverted (Negative)
        inverted = cv2.bitwise_not(enhanced)
        variants.append(cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR))

        # Variant 3: Binary Threshold (Hard edges)
        # Otsu's binarization
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))

        return variants

    def generate_masks(self, input_dir: Path, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        images = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        logger.info(f"Generating masks for {len(images)} frames")

        for img_path in images:
            frame = cv2.imread(str(img_path))
            if frame is None:
                continue

            masks = self._process_batch_with_hybrid_detection([frame])

            mask_name = img_path.name
            if mask_name.endswith('.jpg'):
                mask_name = mask_name[:-4] + '.png'

            if masks:
                cv2.imwrite(str(output_dir / mask_name), masks[0])
            else:
                h, w = frame.shape[:2]
                empty = np.zeros((h, w), dtype=np.uint8)
                cv2.imwrite(str(output_dir / mask_name), empty)

        return output_dir

    def cleanup_temp_dir(self, dir_path: Path):
        if dir_path.exists():
            shutil.rmtree(dir_path)

    def _process_batch_with_hybrid_detection(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        if self.ocr is None:
            return [np.zeros((f.shape[0], f.shape[1]), dtype=np.uint8) for f in frames]

        masks = []
        for frame in frames:
            h_orig, w_orig = frame.shape[:2]
            mask_accum = np.zeros((h_orig * 2, w_orig * 2), dtype=np.uint8)  # Working in 2x scale

            # Generate 3 variants (Normal, Inverted, Binary) - all upscaled 2x
            variants = self._enhance_variants(frame)

            found_something = False

            for i, img_variant in enumerate(variants):
                try:
                    result = self.ocr.ocr(img_variant, cls=True, rec=True)
                    if result and result[0]:
                        found_something = True
                        # logger.debug(f"OCR Pass {i+1} found text!")
                        for line in result[0]:
                            coords = line[0]
                            points = np.array(coords, dtype=np.int32)
                            cv2.fillPoly(mask_accum, [points], 255)
                except Exception:
                    continue

            # Downscale mask back to original size
            mask_final = cv2.resize(mask_accum, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST)

            # Dilation
            if self.mask_dilation > 0 and found_something:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                                   (self.mask_dilation, self.mask_dilation))
                mask_final = cv2.dilate(mask_final, kernel, iterations=1)

            masks.append(mask_final)

        return masks
