import cv2
import numpy as np
from pathlib import Path
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.shared.logging import get_logger

logger = get_logger(__name__)

class MaskGeneratorService:
    def __init__(self, lang: str = 'en', use_gpu: bool = True, **kwargs):
        # Инициализируем наш "Paranoid" OCR
        self.ocr = PaddleWrapper(lang=lang, use_gpu=use_gpu)
        # Размер ядра для расширения маски (fix purple rim)
        self.dilation_kernel_size = kwargs.get('mask_dilation', 10)

    def generate_masks(self, frames_dir: Path, output_dir: Path) -> Path:
        """
        Generates masks for all images in frames_dir and saves them to output_dir.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        
        logger.info(f"Generating masks for {len(frames)} frames...")
        
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue
            
            # 1. OCR Detection (Threshold 0.01 -> Paranoid Mode)
            # PaddleWrapper сам вернет всё, что нашел
            bboxes = self.ocr.detect(img, confidence_threshold=0.01)
            
            # 2. Draw basic mask
            mask = np.zeros(img.shape[:2], dtype=np.uint8)
            for bbox in bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)
            
            # 3. DILATION (Critical Fix for artifacts)
            if self.dilation_kernel_size > 0:
                kernel = np.ones((self.dilation_kernel_size, self.dilation_kernel_size), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            # 4. Save
            cv2.imwrite(str(output_dir / frame_path.name), mask)
            
        return output_dir
