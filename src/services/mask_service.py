import logging
import os
import re
import cv2
import numpy as np
from pathlib import Path
from paddleocr import PaddleOCR
from typing import List, Tuple, Union, Optional, Dict, Any

logger = logging.getLogger(__name__)


class MaskService:
    """
    Ultimate Hybrid MaskService:
    1. PaddleOCR (AI) - for standard text.
    2. Morphological Text Hunter (CV2) - for multicolored/outlined/weird text.
       Detects 'texture clusters' organized in horizontal lines.
    """
    def __init__(self,
                 lang: str = 'ru',
                 mask_dilation: int = 15,
                 use_gpu_for_ocr: bool = False,
                 confidence_threshold: float = 0.1):

        self.lang = lang
        self.mask_dilation = mask_dilation
        self.use_gpu = use_gpu_for_ocr  # Map to internal attribute
        self.confidence_threshold = confidence_threshold

        logger.info(f"Initializing Hybrid MaskService. GPU={self.use_gpu}, Lang={self.lang}")

        # Config for PaddleOCR (High sensitivity)
        self.config = {
            "use_angle_cls": False,
            "lang": self.lang,
            "use_gpu": self.use_gpu,
            "show_log": False,
            "enable_mkldnn": True,
            "det_db_thresh": 0.1,
            "det_db_box_thresh": 0.2,
            "det_db_unclip_ratio": 2.0,
        }

        # Auto-Healing Init
        self.ocr = self._init_ocr_robust(self.config)

        # Force attributes (Safety hack)
        if self.ocr is not None:
            try:
                self.ocr.det_db_thresh = 0.1
                self.ocr.det_db_box_thresh = 0.2
            except Exception:
                pass

    def _init_ocr_robust(self, params: Dict[str, Any]) -> Optional[PaddleOCR]:
        attempts = 0
        max_attempts = len(params) + 2
        current_params = params.copy()

        # Regex to catch argument errors from different library versions
        error_patterns = [
            r"unexpected keyword argument ['\"]([^'\"]+)['\"]",
            r"Unknown argument:?\s+([A-Za-z0-9_]+)",
            r"got an unexpected keyword argument ['\"]([^'\"]+)['\"]"
        ]

        while attempts < max_attempts:
            try:
                return PaddleOCR(**current_params)
            except Exception as e:
                error_msg = str(e)
                bad_arg = None
                for pattern in error_patterns:
                    match = re.search(pattern, error_msg)
                    if match:
                        bad_arg = match.group(1)
                        break

                if bad_arg and bad_arg in current_params:
                    logger.warning(f"PaddleOCR removing bad arg: {bad_arg}")
                    del current_params[bad_arg]
                else:
                    logger.error(f"PaddleOCR init failed: {e}. Switching to CV2-only mode.")
                    return None
            attempts += 1
        return None

    def _morphological_text_hunter(self, image: np.ndarray) -> np.ndarray:
        """
        Pure Computer Vision approach using CLAHE + Adaptive Thresholding + Morphology.
        Finds text regions based on texture density and horizontal alignment.
        """
        # 1. Convert to Gray
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
        # CRITICAL: This pulls details out of dark/colored regions
        clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)

        # 3. Compute Morphological Gradient (Edginess)
        kernel_grad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        grad = cv2.morphologyEx(enhanced, cv2.MORPH_GRADIENT, kernel_grad)

        # 4. Binarize using Adaptive Threshold (Better for gradients than Otsu)
        binary = cv2.adaptiveThreshold(
            grad, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 5. Connect Horizontally (Smear)
        # Text is horizontal. We bridge gaps between letters.
        # Kernel: (30, 1) -> Connect things up to 30px apart horizontally
        kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 1))
        connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_connect)

        # 6. Filter by shape (Keep only bar-like shapes)
        contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        mask = np.zeros_like(gray)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)

            # Subtitle Logic:
            # - Must be somewhat wide (AR > 1.5)
            # - Must not be too small (w > 15, h > 8)
            # - Must not be the whole screen (h < image_h / 3)
            if aspect_ratio > 1.5 and w > 15 and h > 8 and h < (image.shape[0] / 3):
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

        # 7. Dilate final mask slightly to ensure full coverage
        dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 5))
        mask = cv2.dilate(mask, dilate_kernel, iterations=1)

        return mask

    def process_image(self, image_input: Union[str, np.ndarray]) -> Tuple[np.ndarray, List[str]]:
        try:
            # Load Image
            if isinstance(image_input, str):
                if not os.path.exists(image_input):
                    raise FileNotFoundError(f"Image {image_input}")
                img = cv2.imread(image_input)
            else:
                img = image_input

            if img is None: return img, []

            h, w = img.shape[:2]

            # --- LAYER 1: PaddleOCR (The Brain) ---
            mask_ocr = np.zeros((h, w), dtype=np.uint8)
            ocr_hits = 0

            if self.ocr:
                try:
                    # Detection only. Invert image to help with bright text.
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    inverted = cv2.bitwise_not(gray)
                    inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)

                    boxes = self._run_ocr_detection(inverted_bgr)
                    if boxes:
                        ocr_hits = len(boxes)
                        for box in boxes:
                            cv2.fillPoly(mask_ocr, [box], 255)

                        # Dilate OCR result
                        k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                        mask_ocr = cv2.dilate(mask_ocr, k, iterations=1)
                except Exception as e:
                    logger.warning(f"OCR step failed: {e}")

            # --- LAYER 2: Morphological Hunter (The Brawn) ---
            # Finds structure even if OCR fails
            mask_cv = self._morphological_text_hunter(img)

            # --- COMBINE ---
            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)

            # Apply to Image (Black out the detected regions)
            masked_img = img.copy()
            masked_img[final_mask > 0] = (0, 0, 0)

            log_msg = f"Mask generation: OCR found {ocr_hits} regions. Combined with CV2 Morph."
            logger.info(log_msg)

            # Return dummy text list since we skipped recognition
            return masked_img, ["<hybrid_masked>"]

        except Exception as e:
            logger.error(f"Masking failed: {e}", exc_info=True)
            return image_input if isinstance(image_input, np.ndarray) else cv2.imread(image_input), []

    def _run_ocr_detection(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Run OCR detection on image and return list of polygon points.
        Handles different PaddleOCR result structures.
        """
        if self.ocr is None:
            return []
        
        try:
            # Call OCR without extra parameters (default detection + recognition)
            result = self.ocr.ocr(image)
            # result can be list or dict depending on version
            boxes = []
            if isinstance(result, dict):
                # New structure: dict with 'rec_polys' etc.
                if 'rec_polys' in result:
                    polygons = result['rec_polys']
                    for poly in polygons:
                        boxes.append(poly.astype(np.int32))
            elif isinstance(result, list) and len(result) > 0:
                # Old structure: list of [[coordinates], (text, confidence)]
                ocr_result = result[0]  # first element for the image
                if ocr_result is None:
                    return []
                for line in ocr_result:
                    if len(line) > 0:
                        coords = line[0]  # polygon coordinates
                        boxes.append(np.array(coords, dtype=np.int32))
            return boxes
        except Exception as e:
            logger.warning(f"OCR detection failed: {e}")
            return []

    def _process_batch_with_hybrid_detection(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Process a batch of frames using the same hybrid detection logic.
        Returns list of masks (binary uint8).
        """
        masks = []
        for frame in frames:
            h, w = frame.shape[:2]
            mask_ocr = np.zeros((h, w), dtype=np.uint8)
            ocr_hits = 0
            
            if self.ocr:
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    inverted = cv2.bitwise_not(gray)
                    inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
                    boxes = self._run_ocr_detection(inverted_bgr)
                    if boxes:
                        ocr_hits = len(boxes)
                        for box in boxes:
                            cv2.fillPoly(mask_ocr, [box], 255)
                        k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                        mask_ocr = cv2.dilate(mask_ocr, k, iterations=1)
                except Exception as e:
                    logger.warning(f"OCR step failed in batch: {e}")
            
            mask_cv = self._morphological_text_hunter(frame)
            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)
            masks.append(final_mask)
        
        return masks

    def generate_masks(self,
                       input_dir: Union[str, Path],
                       output_dir: Union[str, Path],
                       batch_size: Optional[int] = None) -> Path:
        """
        Generate masks for all frames in input_dir using hybrid detection.
        Saves masks to output_dir and returns output_dir Path.
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
        
        # Load frames in batches
        frames = []
        for frame_path in frame_paths:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                logger.warning(f"Failed to load frame: {frame_path}")
                continue
            frames.append(frame)
        
        # Process all frames at once (or in batches if needed)
        masks = self._process_batch_with_hybrid_detection(frames)
        
        # Save masks
        for idx, mask in enumerate(masks):
            mask_filename = f"mask_{idx:05d}.png"
            mask_path = output_path / mask_filename
            cv2.imwrite(str(mask_path), mask)
        
        logger.info(f"Saved {len(masks)} masks to {output_path}")
        return output_path

    def cleanup_temp_dir(self, dir_path: Union[str, Path]):
        """
        Remove temporary directory created during mask generation.
        """
        import shutil
        dir_path = Path(dir_path)
        if dir_path.exists():
            shutil.rmtree(dir_path)
            logger.info(f"Cleaned up temporary directory: {dir_path}")
        else:
            logger.warning(f"Directory does not exist: {dir_path}")


# Alias for backward compatibility
MaskGeneratorService = MaskService
