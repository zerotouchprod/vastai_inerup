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
       - 0.6 = Bottom 60% of screen (default).
       - 1.0 = Full screen (no filtering).
    2. Detects Aggressively (0.15 threshold + CLAHE).
    3. Discards any text found physically above the ROI limit.

    Supported GPU: RTX 3060 - RTX 5090 (6GB - 24GB VRAM)
    """

    # Default ROI: bottom 60% of screen (covers subtitles slightly below center)
    DEFAULT_ROI_FACTOR = 0.6

    def __init__(self, mask_service, inpainter, lang='ru', roi_factor=None):
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
        # Если пришло строкой "bottom" -> 0.6, "full" -> 1.0
        if roi_factor is None:
            self.roi_height_factor = self.DEFAULT_ROI_FACTOR
        elif isinstance(roi_factor, str):
            if roi_factor.lower() == "full":
                self.roi_height_factor = 1.0
            elif roi_factor.lower() == "bottom":
                self.roi_height_factor = self.DEFAULT_ROI_FACTOR
            else:
                try:
                    self.roi_height_factor = float(roi_factor)
                except:
                    self.roi_height_factor = self.DEFAULT_ROI_FACTOR
        else:
            self.roi_height_factor = float(roi_factor) if roi_factor else self.DEFAULT_ROI_FACTOR

        # Statistics for logging
        self._stats = {
            'total_detections': 0,
            'total_kept': 0,
            'total_filtered': 0,
            'frames_with_text': 0
        }

        logger.info(f"SubtitleRemoverService initialized. ROI: Bottom {int(self.roi_height_factor*100)}% of screen")

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
        Returns: (is_in_roi: bool, center_y: float, roi_limit: float)
        """
        # Если ROI = 1.0 (Full), фильтрация отключена
        if self.roi_height_factor >= 0.99:
            return True, 0, 0

        points = np.array(box, dtype=np.int32)
        center_y = np.mean(points[:, 1])
        
        # Граница: Высота * (1 - 0.6) = Точка начала нижних 60%
        roi_limit = img_height * (1.0 - self.roi_height_factor)
        
        return center_y > roi_limit, center_y, roi_limit

    def _merge_detections(self, bboxes1: list, bboxes2: list) -> list:
        """Merge detections from two OCR passes, removing duplicates by IoU."""
        if not bboxes1:
            return bboxes2 or []
        if not bboxes2:
            return bboxes1

        merged = list(bboxes1)

        for bbox2 in bboxes2:
            is_duplicate = False
            pts2 = np.array(bbox2['points'])
            x2_min, y2_min = pts2.min(axis=0)
            x2_max, y2_max = pts2.max(axis=0)

            for bbox1 in bboxes1:
                pts1 = np.array(bbox1['points'])
                x1_min, y1_min = pts1.min(axis=0)
                x1_max, y1_max = pts1.max(axis=0)

                # Calculate IoU
                inter_x1 = max(x1_min, x2_min)
                inter_y1 = max(y1_min, y2_min)
                inter_x2 = min(x1_max, x2_max)
                inter_y2 = min(y1_max, y2_max)

                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                    area1 = (x1_max - x1_min) * (y1_max - y1_min)
                    area2 = (x2_max - x2_min) * (y2_max - y2_min)
                    iou = inter_area / (area1 + area2 - inter_area + 1e-6)

                    if iou > 0.3:  # Считаем дубликатом если IoU > 30%
                        is_duplicate = True
                        break

            if not is_duplicate:
                merged.append(bbox2)

        return merged

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
        """Generate binary masks with ROI filtering and detailed logging."""
        roi_pct = int(self.roi_height_factor * 100)
        logger.info(f"Generating masks (ROI: bottom {roi_pct}% of screen)...")

        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")
        
        # Reset statistics
        self._stats = {
            'total_detections': 0,
            'total_kept': 0,
            'total_filtered': 0,
            'frames_with_text': 0,
            'confidence_min': 1.0,
            'confidence_max': 0.0,
            'confidence_sum': 0.0
        }

        total_frames = len(frames)
        log_interval = max(1, total_frames // 10)  # Log every 10% progress

        # Aggressive OCR threshold for subtitle detection (lower = more detections)
        # 0.05 catches short words like "на", "и", "в" that 0.15 misses
        OCR_THRESHOLD = 0.05

        for idx, frame_path in enumerate(frames):
            img = cv2.imread(str(frame_path))
            if img is None:
                continue

            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            
            # А. Улучшаем для OCR
            enhanced_img = self._enhance_image_for_ocr(img)
            
            # Б. Агрессивная детекция: запускаем OCR на ОБОИХ изображениях и объединяем
            # Это увеличивает шанс поймать короткие слова типа "на", "и"
            bboxes_enhanced = self.ocr.detect(enhanced_img, confidence_threshold=OCR_THRESHOLD)
            bboxes_original = self.ocr.detect(img, confidence_threshold=OCR_THRESHOLD)

            # Объединяем результаты (убираем дубликаты по IoU)
            bboxes = self._merge_detections(bboxes_enhanced, bboxes_original)

            if not bboxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue
            
            # Track confidence scores
            for bbox in bboxes:
                conf = bbox.get('confidence', 0)
                self._stats['confidence_min'] = min(self._stats['confidence_min'], conf)
                self._stats['confidence_max'] = max(self._stats['confidence_max'], conf)
                self._stats['confidence_sum'] += conf

            detected_count = len(bboxes)
            self._stats['total_detections'] += detected_count

            # В. ФИЛЬТРАЦИЯ ПО ROI (Отсекаем глаза/волосы сверху)
            valid_boxes = []
            filtered_boxes = []
            for bbox in bboxes:
                is_in_roi, center_y, roi_limit = self._is_box_in_roi(bbox['points'], h)
                if is_in_roi:
                    valid_boxes.append(bbox)
                else:
                    filtered_boxes.append({
                        'text': bbox.get('text', '?')[:20],
                        'center_y': center_y,
                        'roi_limit': roi_limit
                    })

            kept_count = len(valid_boxes)
            filtered_count = detected_count - kept_count

            self._stats['total_kept'] += kept_count
            self._stats['total_filtered'] += filtered_count

            if kept_count > 0:
                self._stats['frames_with_text'] += 1

            # Debug log for frames with filtered boxes
            if filtered_count > 0 and logger.isEnabledFor(10):  # DEBUG level
                for fb in filtered_boxes[:3]:  # Max 3 examples
                    logger.debug(f"[Frame {idx}] Filtered: '{fb['text']}' center_y={fb['center_y']:.0f} < roi_limit={fb['roi_limit']:.0f}")

            if not valid_boxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # Г. Рисуем маску
            for bbox in valid_boxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)
            
            # Д. Mega Dilation (расширяем маску чтобы захватить остатки текста и свечение)
            # Увеличен с 25x25 до 35x35 для лучшего покрытия
            kernel = np.ones((35, 35), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)
            
            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
            
            # Progress logging
            if (idx + 1) % log_interval == 0:
                progress = (idx + 1) / total_frames * 100
                logger.info(f"Mask generation progress: {progress:.0f}% ({idx + 1}/{total_frames})")

            # GPU memory cleanup every 50 frames (helps on 6GB GPUs like 3060)
            if (idx + 1) % 50 == 0:
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

        # Final summary
        avg_conf = (self._stats['confidence_sum'] / self._stats['total_detections']
                   if self._stats['total_detections'] > 0 else 0)

        logger.info(f"Mask generation complete:")
        logger.info(f"  - Frames processed: {total_frames}")
        logger.info(f"  - Frames with text: {self._stats['frames_with_text']}")
        logger.info(f"  - Total detections: {self._stats['total_detections']}")
        logger.info(f"  - Kept (in ROI): {self._stats['total_kept']}")
        logger.info(f"  - Filtered (outside ROI): {self._stats['total_filtered']}")
        if self._stats['total_detections'] > 0:
            logger.info(f"  - Confidence: min={self._stats['confidence_min']:.2f}, "
                       f"max={self._stats['confidence_max']:.2f}, avg={avg_conf:.2f}")

# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass
    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")
