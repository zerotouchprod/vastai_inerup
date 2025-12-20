import logging
import os
import re
import cv2
import numpy as np
from paddleocr import PaddleOCR
from typing import List, Tuple, Union, Optional, Dict, Any

logger = logging.getLogger(__name__)


class MaskGeneratorService:
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
        self.use_gpu = use_gpu_for_ocr  # Use GPU if requested
        self.confidence_threshold = confidence_threshold

        logger.info(f"Initializing Hybrid MaskService (AI + CV2). GPU={self.use_gpu}")

        # Config for PaddleOCR (Low threshold to catch anything resembling text)
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
        
        # Force attributes just in case
        if self.ocr is not None:
            try:
                self.ocr.det_db_thresh = 0.1
                self.ocr.det_db_box_thresh = 0.2
            except:
                pass

    def _init_ocr_robust(self, params: Dict[str, Any]) -> Optional[PaddleOCR]:
        attempts = 0
        max_attempts = len(params) + 2 
        current_params = params.copy()
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
                    # If we can't init, we will just use CV2 fallback silently
                    logger.error(f"PaddleOCR died: {e}. Switching to pure CV2 mode.")
                    return None 
            attempts += 1
        return None

    def _morphological_text_hunter(self, image: np.ndarray) -> np.ndarray:
        """
        Pure Computer Vision approach to find text regions based on texture and shape.
        Works for multicolored text where OCR fails.
        """
        # 1. Convert to Gray
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # 2. Compute Morphological Gradient (Edginess)
        # This highlights boundaries of letters regardless of color
        kernel_grad = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel_grad)

        # 3. Binarize (Keep strong edges)
        _, binary = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # 4. Connect Horizontally (Smear)
        # Text is letters close to each other horizontally. We bridge the gaps.
        # Kernel is Wide (25) and Short (1)
        kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
        connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_connect)

        # 5. Filter by shape (Keep only bar-like shapes)
        contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        mask = np.zeros_like(gray)
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            
            # Subtitles are usually wide (AR > 2) and not tiny
            if aspect_ratio > 1.5 and w > 20 and h > 8:
                cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)
        
        # 6. Dilate final mask slightly to ensure coverage
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
                    # Detection only, no text recognition needed
                    # We invert image for better detection of bright text
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    inverted = cv2.bitwise_not(gray)
                    inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
                    
                    result = self.ocr.ocr(inverted_bgr, det=True, rec=False, cls=False)
                    boxes = result[0] if (isinstance(result, list) and len(result) > 0) else []
                    
                    if boxes:
                        ocr_hits = len(boxes)
                        for box in boxes:
                            points = np.array(box, dtype=np.int32)
                            cv2.fillPoly(mask_ocr, [points], 255)
                            
                        # Dilate OCR result using mask_dilation
                        k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                        mask_ocr = cv2.dilate(mask_ocr, k, iterations=1)
                except Exception as e:
                    logger.warning(f"OCR step failed: {e}")

            # --- LAYER 2: Morphological Hunter (The Brawn) ---
            # Finds structure even if OCR fails
            mask_cv = self._morphological_text_hunter(img)
            
            # --- COMBINE ---
            # If OCR found nothing, we rely 100% on CV. 
            # If OCR found something, we combine them (union).
            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)

            # Apply to Image
            masked_img = img.copy()
            masked_img[final_mask > 0] = (0, 0, 0)
            
            log_msg = f"Mask generation: OCR found {ocr_hits} regions."
            if ocr_hits == 0:
                log_msg += " Using purely Morphological/CV detection."
            logger.info(log_msg)

            return masked_img, ["<masked_regions>"]

        except Exception as e:
            logger.error(f"Masking failed: {e}", exc_info=True)
            # Return original if everything explodes
            return image_input if isinstance(image_input, np.ndarray) else cv2.imread(image_input), []

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
                    result = self.ocr.ocr(inverted_bgr, det=True, rec=False, cls=False)
                    boxes = result[0] if (isinstance(result, list) and len(result) > 0) else []
                    if boxes:
                        ocr_hits = len(boxes)
                        for box in boxes:
                            points = np.array(box, dtype=np.int32)
                            cv2.fillPoly(mask_ocr, [points], 255)
                        k = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                        mask_ocr = cv2.dilate(mask_ocr, k, iterations=1)
                except Exception as e:
                    logger.warning(f"OCR step failed in batch: {e}")
            
            mask_cv = self._morphological_text_hunter(frame)
            final_mask = cv2.bitwise_or(mask_ocr, mask_cv)
            masks.append(final_mask)
        
        return masks

    def generate_masks(self, video_path: str, roi: Optional[Tuple[int, int, int, int]] = None,
                       start_frame: int = 0, end_frame: Optional[int] = None,
                       frame_skip: int = 1, output_dir: Optional[str] = None) -> List[str]:
        """
        Generate masks for a video using hybrid detection.
        """
        import tempfile
        from src.infrastructure.video_reader import VideoReader
        
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix='mask_')
        
        reader = VideoReader(video_path, roi=roi)
        frames = []
        frame_indices = []
        
        for idx, frame in enumerate(reader):
            if idx < start_frame:
                continue
            if end_frame is not None and idx >= end_frame:
                break
            if (idx - start_frame) % frame_skip != 0:
                continue
            frames.append(frame)
            frame_indices.append(idx)
        
        masks = self._process_batch_with_hybrid_detection(frames)
        
        mask_paths = []
        for idx, mask in zip(frame_indices, masks):
            mask_path = os.path.join(output_dir, f"mask_{idx:06d}.png")
            cv2.imwrite(mask_path, mask)
            mask_paths.append(mask_path)
        
        return mask_paths

    def cleanup_temp_dir(self, dir_path: str):
        """
        Remove temporary directory created during mask generation.
        """
        import shutil
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
            logger.info(f"Cleaned up temporary directory: {dir_path}")
        else:
            logger.warning(f"Directory does not exist: {dir_path}")
