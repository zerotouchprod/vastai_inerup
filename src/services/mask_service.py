import logging
import os
import re
import cv2
import numpy as np
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
                 use_gpu: bool = False,
                 lang: str = 'ru',
                 mask_dilation: int = 15):

        self.use_gpu = use_gpu
        self.lang = lang
        self.mask_dilation = mask_dilation

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

                    # det=True, rec=False, cls=False
                    result = self.ocr.ocr(inverted_bgr, det=True, rec=False, cls=False)
                    boxes = result[0] if (isinstance(result, list) and len(result) > 0) else []

                    if boxes:
                        ocr_hits = len(boxes)
                        for box in boxes:
                            points = np.array(box, dtype=np.int32)
                            cv2.fillPoly(mask_ocr, [points], 255)

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

    def generate_masks(self,
                       frames: List[np.ndarray],
                       output_dir: str) -> List[str]:
        """
        Batch processing helper. Saves masks to output_dir.
        """
        os.makedirs(output_dir, exist_ok=True)
        mask_paths = []

        logger.info(f"Generating masks for {len(frames)} frames using Hybrid Engine...")

        for idx, frame in enumerate(frames):
            # Generate mask (we only need the binary mask here, not the blacked-out image)
            # Re-using internal logic for efficiency
            mask_cv = self._morphological_text_hunter(frame)

            mask_ocr = np.zeros(frame.shape[:2], dtype=np.uint8)
            if self.ocr:
                try:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    inverted = cv2.bitwise_not(gray)
                    inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
                    result = self.ocr.ocr(inverted_bgr, det=True, rec=False, cls=False)
                    boxes = result[0] if (isinstance(result, list) and len(result) > 0) else []
                    for box in boxes:
                        points = np.array(box, dtype=np.int32)
                        cv2.fillPoly(mask_ocr, [points], 255)
                    k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                    mask_ocr = cv2.dilate(mask_ocr, k, iterations=1)
                except:
                    pass

            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)

            mask_filename = f"mask_{idx:05d}.png"
            mask_path = os.path.join(output_dir, mask_filename)
            cv2.imwrite(mask_path, final_mask)
            mask_paths.append(mask_path)

        return mask_paths