import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Dict, Any, Union

# Попытка импорта EasyOCR. Если не установлен, будет ошибка при инициализации,
# но не при загрузке модуля (чтобы не ломать тесты/CI).
try:
    import easyocr
except ImportError:
    easyocr = None

logger = logging.getLogger(__name__)

class PaddleWrapper:
    """
    Wrapper that mimics PaddleOCR interface but uses EasyOCR under the hood.
    This solves the Segmentation Fault issues caused by PaddlePaddle C++ conflicts.
    """
    def __init__(self, lang='en', use_gpu=True):
        if easyocr is None:
            raise ImportError("EasyOCR not installed. Please run: pip install easyocr")

        # EasyOCR использует PyTorch и CUDA, конфликтов не будет.
        # Если use_gpu=True, он будет использовать ту же GPU, что и остальной проект.
        self.use_gpu = use_gpu
        self.lang = lang
        
        # Маппинг языков (Paddle -> EasyOCR)
        # EasyOCR поддерживает списки языков ['ru', 'en']
        langs_list = [lang] if lang != 'en' else ['en']
        if 'en' not in langs_list:
            langs_list.append('en') # Всегда добавляем английский для лучшей работы модели
            
        logger.info(f"Initializing EasyOCR (langs={langs_list}, gpu={use_gpu})...")
        
        # Инициализация Reader. 
        # При первом запуске он скачает модели в ~/.EasyOCR/model, если их там нет.
        self.reader = easyocr.Reader(
            langs_list, 
            gpu=use_gpu,
            verbose=False,
            quantize=False # Отключаем квантование для максимальной точности
        )

    def detect(self, image: Union[str, np.ndarray], confidence_threshold: float = 0.0) -> List[Dict[str, Any]]:
        """
        Detect text using EasyOCR and adapt output to match Paddle format.
        
        Args:
            image: Path to image or numpy array (BGR).
            confidence_threshold: Min confidence to return box.
            
        Returns:
            List of dicts: {'points': [[x,y]...], 'text': str, 'confidence': float}
        """
        # 1. Загрузка изображения
        if isinstance(image, str):
            img = cv2.imread(image)
            if img is None:
                logger.error(f"[ERROR] Could not read image: {image}")
                return []
            # EasyOCR ожидает RGB, OpenCV грузит BGR
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        elif isinstance(image, np.ndarray):
            # Предполагаем, что вход уже BGR (как принято в OpenCV)
            img = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            return []

        # 2. Инференс
        # EasyOCR returns list of tuples: (bbox, text, prob)
        # bbox = [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
        try:
            results = self.reader.readtext(img)
        except Exception as e:
            logger.error(f"EasyOCR inference failed: {e}")
            return []

        bboxes = []
        
        # 3. Адаптация формата под PaddleOCR (чтобы не ломать mask_service)
        for (bbox, text, prob) in results:
            if prob < confidence_threshold:
                continue
                
            # EasyOCR возвращает int coordinates, но в формате list of lists
            # Нам нужно [[x,y], [x,y]...]
            # Иногда bbox это numpy array, иногда list
            points = [[int(pt[0]), int(pt[1])] for pt in bbox]
            
            bboxes.append({
                "points": points,
                "text": text,
                "confidence": float(prob)
            })

        logger.info(f"EasyOCR found {len(bboxes)} text blocks (thresh={confidence_threshold})")
        return bboxes

    # --- Backward compatibility methods (Legacy) ---
    
    def detect_text(self, frame: np.ndarray, confidence_threshold=0.0) -> list:
        """
        Returns list of BBox [x1, y1, x2, y2] for found text.
        Compatible with old cleaners.
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


# Keep ThreadSafeOCR for backward compatibility with existing tests/factories
class ThreadSafeOCR(PaddleWrapper):
    """
    Backward compatibility wrapper. 
    Previously used for threading, now just inherits EasyOCR logic.
    """
    def __init__(self, lang: str = 'en', use_gpu_for_ocr: bool = False, use_angle_cls: bool = False):
        use_gpu = use_gpu_for_ocr
        super().__init__(lang=lang, use_gpu=use_gpu)

    def process_batch(self, images: List[np.ndarray], confidence_threshold: float = 0.3) -> List[np.ndarray]:
        # Legacy method support
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
        
        logger.info(f"Generating masks for {len(frames)} frames using EasyOCR...")
        
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
