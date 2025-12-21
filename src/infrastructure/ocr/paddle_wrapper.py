import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Union
from paddleocr import PaddleOCR
from src.shared.logging import get_logger

logger = get_logger(__name__)


class PaddleWrapper:
    def __init__(self, lang='en', use_gpu=True):
        # --- FORCE CPU FIX ---
        # We forcibly set use_gpu=False to prevent Segmentation Faults caused by
        # conflicts between PaddlePaddle-GPU and the PyTorch Docker CUDA environment.
        # OCR on CPU is fast enough (~0.1s/frame) and stable.
        self.use_gpu = False
        self.lang = lang

        logger.info(f"Initializing PaddleOCR (lang={lang}, gpu={self.use_gpu}) [FORCED CPU MODE]")

        # PARANOID MODE: Low thresholds to detect faint/blurry text
        # Use robust initialization with auto-healing for unknown parameters
        self.ocr = self._init_paddleocr_robust(
            use_angle_cls=True,
            lang=lang,
            use_gpu=self.use_gpu,  # forcing False here
            show_log=False,  # Reduce internal spam (may be removed if not supported)
            det_db_thresh=0.05,  # Very sensitive pixel detection
            det_db_box_thresh=0.1,  # Keep even low-conf boxes
            det_db_unclip_ratio=1.6,  # Expand boxes slightly
            rec_batch_num=6  # Batch size for recognition
        )

    def _init_paddleocr_robust(self, **kwargs):
        """
        Initialize PaddleOCR with automatic removal of unsupported parameters.
        
        Args:
            **kwargs: Parameters to pass to PaddleOCR constructor.
            
        Returns:
            PaddleOCR instance.
        """
        import re
        
        attempts = 0
        max_attempts = len(kwargs) + 2
        current_params = kwargs.copy()
        
        # Regex patterns to detect unsupported argument errors
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
                    logger.warning(f"PaddleOCR removing unsupported argument: {bad_arg}")
                    del current_params[bad_arg]
                else:
                    logger.error(f"PaddleOCR initialization failed: {e}")
                    raise
            attempts += 1
        
        # If we get here, all attempts failed
        raise RuntimeError(f"Failed to initialize PaddleOCR after {max_attempts} attempts")

    def detect(self, image: Union[str, np.ndarray], confidence_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """
        Detect text in image and return list of text bounding boxes.
        Default confidence set to 0.0 to allow external filtering.
        """
        # 1. Read image
        if isinstance(image, str):
            img = cv2.imread(image)
            if img is None:
                logger.error(f"[ERROR] Could not read image: {image}")
                return []
        else:
            img = image

        if img is None:
            return []

        # 2. Run OCR
        try:
            # cls=True needed for rotated text
            result = self.ocr.ocr(img, cls=True)
        except Exception as e:
            logger.error(f"PaddleOCR internal error: {e}")
            return []

        if not result:
            return []

        # 3. Normalize structure (Paddle returns [Page1, Page2...])
        if result[0] is None:
            return []

        ocr_data = result[0]
        bboxes = []

        for line in ocr_data:
            # line structure: [[[x1, y1], [x2, y2], ...], ("text", confidence)]
            try:
                coords = line[0]
                text_info = line[1]

                text_content = text_info[0]
                conf = text_info[1]

                # Filter by confidence
                if conf < confidence_threshold:
                    continue

                # Convert float coordinates to int
                points = [[int(p[0]), int(p[1])] for p in coords]

                bboxes.append({
                    "points": points,
                    "text": text_content,
                    "confidence": conf
                })
            except Exception as e:
                logger.warning(f"Error parsing OCR line: {line}. Error: {e}")
                continue

        logger.info(f"PaddleWrapper found {len(bboxes)} text blocks (thresh={confidence_threshold})")
        return bboxes

    def detect_text(self, frame: np.ndarray, confidence_threshold=0.0) -> list:
        """
        Returns list of BBox [x1, y1, x2, y2] for found text.
        (Backward compatibility method)
        """
        detections = self.detect(frame, confidence_threshold)
        bboxes = []
        for det in detections:
            points = det["points"]
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            x1, y1 = min(xs), min(ys)
            x2, y2 = max(xs), max(ys)
            bboxes.append([x1, y1, x2, y2])
        return bboxes


# Keep ThreadSafeOCR for backward compatibility with existing tests
class ThreadSafeOCR(PaddleWrapper):
    """Backward compatibility wrapper for ThreadSafeOCR."""

    def __init__(self, lang: str = 'en', use_gpu_for_ocr: bool = False, use_angle_cls: bool = False):
        use_gpu = use_gpu_for_ocr
        super().__init__(lang=lang, use_gpu=use_gpu)

    def process_batch(self, images: List[np.ndarray], confidence_threshold: float = 0.3) -> List[np.ndarray]:
        import warnings
        warnings.warn("ThreadSafeOCR.process_batch is deprecated.", DeprecationWarning)

        masks = []
        for img in images:
            bboxes = self.detect_text(img, confidence_threshold)
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            for bbox in bboxes:
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
            masks.append(mask)
        return masks

    def create_masks_for_directory(self, input_dir: Path, output_dir: Path,
                                   batch_size: int = 8, confidence_threshold: float = 0.3) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))

        logger.info(f"Generating masks for {len(frames)} frames...")

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue

            bboxes = self.detect_text(img, confidence_threshold)
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            for bbox in bboxes:
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)

            mask_path = output_dir / frame_path.name
            cv2.imwrite(str(mask_path), mask)

        return output_dir
