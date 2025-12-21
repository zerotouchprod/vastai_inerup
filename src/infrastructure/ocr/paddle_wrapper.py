import cv2
import numpy as np
from pathlib import Path
from typing import List
from paddleocr import PaddleOCR
from src.shared.logging import get_logger

logger = get_logger(__name__)

class PaddleWrapper:
    def __init__(self, lang='en', use_gpu=True):
        self.ocr = PaddleOCR(use_angle_cls=True, lang=lang)

    def detect_text(self, frame: np.ndarray, confidence_threshold=0.6) -> list:
        """
        Возвращает список BBox [x1, y1, x2, y2] для найденного текста.
        """
        result = self.ocr.ocr(frame, cls=True)
        bboxes = []
        if result and result[0]:
            for line in result[0]:
                # line format: [[[x1,y1],[x2,y2],[x3,y3],[x4,y4]], (text, conf)]
                points = line[0]
                conf = line[1][1]
                
                if conf < confidence_threshold:
                    continue
                
                # Convert polygon to bounding box for SAM 2
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
        # Map parameters to PaddleWrapper
        use_gpu = use_gpu_for_ocr
        super().__init__(lang=lang, use_gpu=use_gpu)
        
    def process_batch(self, images: List[np.ndarray], confidence_threshold: float = 0.3) -> List[np.ndarray]:
        """
        Process batch of images and return masks.
        For backward compatibility only.
        """
        import warnings
        warnings.warn("ThreadSafeOCR.process_batch is deprecated. Use PaddleWrapper.detect_text instead.", DeprecationWarning)
        
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
        """
        Create masks for all frames in directory.
        For backward compatibility only.
        """
        import warnings
        warnings.warn("ThreadSafeOCR.create_masks_for_directory is deprecated.", DeprecationWarning)
        
        from pathlib import Path
        import cv2
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get all frame files
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            raise ValueError(f"No frames found in directory: {input_dir}")
        
        logger.info(f"Generating masks for {len(frames)} frames...")
        
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None:
                continue
                
            bboxes = self.detect_text(img, confidence_threshold)
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            for bbox in bboxes:
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
            
            mask_path = output_dir / frame_path.name
            cv2.imwrite(str(mask_path), mask)
        
        return output_dir
