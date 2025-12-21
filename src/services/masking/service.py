import cv2
import shutil
from pathlib import Path
from typing import Dict, List
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_adapter import Sam2Adapter
from src.shared.logging import get_logger
from tqdm import tqdm

logger = get_logger(__name__)

class TextMaskService:
    def __init__(self, ocr: PaddleWrapper, sam2: Sam2Adapter):
        self.ocr = ocr
        self.sam2 = sam2

    def create_video_masks(self, video_path: Path, output_dir: Path, roi: str = "bottom") -> Path:
        """
        Генерирует последовательность масок для видео.
        1. Проходит по видео, запуская OCR каждые N кадров (key frames).
        2. Передает найденные боксы в SAM 2 для точной сегментации всех кадров.
        """
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        # Стратегия: OCR запускаем каждые 1 секунду (или каждые 0.5 сек для динамики)
        # Для TikTok лучше чаще, например каждые 10-15 кадров.
        ocr_interval = int(fps / 2) if fps > 0 else 15
        
        bboxes_by_frame: Dict[int, List[List[float]]] = {}
        
        logger.info(f"Starting OCR detection (Interval: every {ocr_interval} frames)...")
        
        current_frame = 0
        with tqdm(total=total_frames, desc="OCR Scanning") as pbar:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Запускаем OCR только на ключевых кадрах
                if current_frame % ocr_interval == 0:
                    # TODO: Применить ROI (обрезать frame) перед OCR для ускорения
                    # Здесь упрощенно - весь кадр
                    detected_boxes = self.ocr.detect_text(frame)
                    if detected_boxes:
                        bboxes_by_frame[current_frame] = detected_boxes
                
                current_frame += 1
                pbar.update(1)
        
        cap.release()
        
        if not bboxes_by_frame:
            logger.warning("No text detected in video!")
            # Создаем пустые маски, чтобы пайплайн не упал
            return self._create_empty_masks(total_frames, output_dir, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

        # Запускаем SAM 2
        logger.info(f"Detected text on {len(bboxes_by_frame)} keyframes. Starting SAM 2...")
        return self.sam2.generate_masks(str(video_path), bboxes_by_frame, output_dir)

    def _create_empty_masks(self, count, out_dir, w, h):
        out_dir.mkdir(parents=True, exist_ok=True)
        # Просто черные картинки
        import numpy as np
        from PIL import Image
        black = np.zeros((h, w), dtype=np.uint8)
        img = Image.fromarray(black)
        for i in range(count):
            img.save(out_dir / f"{i:05d}.png")
        return out_dir
