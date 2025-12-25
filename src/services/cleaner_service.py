import tempfile
import shutil
import cv2
import numpy as np
from pathlib import Path
from src.shared.logging import get_logger

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

logger = get_logger(__name__)

class SubtitleRemoverService:
    """
    Dynamic ROI-Based Cleaner.
    
    1. Accepts 'roi_factor' (float) from CLI.
       - 0.35 = Bottom 35% of screen.
       - 1.0 = Full screen (no filtering).
    2. Detects Aggressively (0.15 threshold + CLAHE).
    3. Discards any text found physically above the ROI limit.
    """
    def __init__(self, mask_service, inpainter, lang='ru', roi_factor=0.35):
        self.inpainter = inpainter
        
        # Обработка языков
        if isinstance(lang, str):
            langs = [l.strip() for l in lang.split(',')]
        else:
            langs = lang if isinstance(lang, list) else ['en']
        if 'en' not in langs: langs.append('en')
            
        self.ocr_langs = langs
        self.ocr = PaddleWrapper(lang=self.ocr_langs, use_gpu=True)
        
        # ПАРАМЕТР ROI: Прокидывается из CLI
        # Если пришло строкой "bottom" -> 0.35, "full" -> 1.0
        if isinstance(roi_factor, str):
            if roi_factor.lower() == "full":
                self.roi_height_factor = 1.0
            elif roi_factor.lower() == "bottom":
                self.roi_height_factor = 0.35
            else:
                try:
                    self.roi_height_factor = float(roi_factor)
                except:
                    self.roi_height_factor = 0.35 # Fallback
        else:
            self.roi_height_factor = float(roi_factor) if roi_factor else 0.35
            
        logger.info(f"SubtitleRemoverService initialized. ROI: Bottom {int(self.roi_height_factor*100)}%")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """CLAHE: Вытягивает скрытый текст."""
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return final
        except Exception:
            return img

    def _is_box_in_roi(self, box, img_height):
        """
        Проверяет, попадает ли центр текста в нижнюю зону экрана.
        """
        # Если ROI = 1.0 (Full), фильтрация отключена
        if self.roi_height_factor >= 0.99:
            return True
            
        points = np.array(box, dtype=np.int32)
        center_y = np.mean(points[:, 1])
        
        # Граница: Высота * (1 - 0.35) = Точка начала нижних 35%
        roi_limit = img_height * (1.0 - self.roi_height_factor)
        
        return center_y > roi_limit

    def process(self, input_path, output_path: Path, **kwargs):
        logger.info(f"Removing subtitles from {input_path}")
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                mask_dir = temp_path / "masks"
                mask_dir.mkdir()
                
                frames_dir = None
                
                # 1. Подготовка кадров
                if isinstance(input_path, list):
                    frames_dir = temp_path / "input_frames"
                    frames_dir.mkdir()
                    for i, frame_path in enumerate(input_path):
                        p = Path(frame_path)
                        shutil.copy(p, frames_dir / f"frame_{i:06d}{p.suffix}")
                else:
                    input_path = Path(input_path)
                    if input_path.is_dir():
                        frames_dir = input_path
                    else:
                        from src.infrastructure.media.ffmpeg import FFmpegExtractor
                        extractor = FFmpegExtractor()
                        frames_dir = temp_path / "extracted_frames"
                        frames_dir.mkdir()
                        extractor.extract_frames(input_path, frames_dir)

                # 2. Генерация масок с учетом ROI
                self._generate_roi_masks(frames_dir, mask_dir)
                
                # 3. Inpainting
                result_path = self.inpainter.process(frames_dir, mask_dir, output_path)
            
            class SimpleResult:
                def __init__(self, success=True, output_path=None):
                    self.success = success
                    self.output_path = output_path
            
            return SimpleResult(success=True, output_path=result_path)
            
        except Exception as e:
            logger.error(f"Subtitle removal failed: {e}", exc_info=True)
            class SimpleResult:
                def __init__(self, success=False, output_path=None, errors=None):
                    self.success = success
                    self.output_path = output_path
                    self.errors = [str(e)] if errors is None else errors
            return SimpleResult(success=False, output_path=None, errors=[str(e)])

    def _generate_roi_masks(self, frames_dir: Path, mask_dir: Path):
        logger.info(f"Generating binary masks (ROI Strategy)...")
        
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")
        
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue
            
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            
            # А. Улучшаем
            enhanced_img = self._enhance_image_for_ocr(img)
            
            # Б. Детектим ВСЁ (агрессивно)
            bboxes = self.ocr.detect(enhanced_img, confidence_threshold=0.15)
            
            # Фолбэк на оригинал
            if not bboxes:
                bboxes = self.ocr.detect(img, confidence_threshold=0.15)
            
            if not bboxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue
            
            # В. ФИЛЬТРАЦИЯ ПО ROI (Отсекаем глаза/волосы сверху)
            valid_boxes = []
            for bbox in bboxes:
                if self._is_box_in_roi(bbox['points'], h):
                    valid_boxes.append(bbox)
            
            if not valid_boxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # Г. Рисуем маску
            for bbox in valid_boxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)
            
            # Д. Mega Dilation (от фиолетового тумана)
            kernel = np.ones((25, 25), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)
            
            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
            
        logger.info(f"Generated {len(frames)} masks")

# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass
    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")
