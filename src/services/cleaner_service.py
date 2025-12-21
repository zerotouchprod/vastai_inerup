import tempfile
import shutil
import cv2
import numpy as np
from pathlib import Path
from src.shared.logging import get_logger

# Import Adapters
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

logger = get_logger(__name__)


class SubtitleRemoverService:
    """
    TEMPORAL CONSISTENCY CLEANER.

    Philosophy: "Text is static, Noise is dynamic."

    1. Detection Phase: Scans ALL frames with very low threshold (0.1) + CLAHE.
       Catches everything: "НА", "РОДИЛСЯ", eyes, hair, noise.

    2. Temporal Filter Phase:
       Analyses the timeline. If a bounding box appears in the same coordinates
       across multiple frames (Radius of 10px), it is confirmed as Text.
       If it appears fleetingly or moves erratically, it is discarded as Noise.

    3. Masking Phase:
       Applies MASSIVE dilation only to confirmed text regions to remove glow/shadows.
    """

    def __init__(self, mask_service, inpainter, lang='ru'):
        self.inpainter = inpainter

        # Динамическая обработка языков
        if isinstance(lang, str):
            langs = [l.strip() for l in lang.split(',')]
        else:
            langs = lang if isinstance(lang, list) else ['en']

        if 'en' not in langs: langs.append('en')

        self.ocr_langs = langs
        # Используем GPU
        self.ocr = PaddleWrapper(lang=self.ocr_langs, use_gpu=True)
        logger.info(f"SubtitleRemoverService initialized (Mode: TEMPORAL CONSISTENCY)")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """CLAHE: Делает невидимый текст видимым."""
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            # ClipLimit 4.0 - агрессивно вытягиваем детали
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return final
        except Exception:
            return img

    def _calculate_iou(self, boxA, boxB):
        """Считает пересечение двух боксов (Intersection over Union)."""
        # box: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        # Нам нужны min_x, min_y, max_x, max_y
        polyA = np.array(boxA, dtype=np.int32)
        polyB = np.array(boxB, dtype=np.int32)

        xA = max(np.min(polyA[:, 0]), np.min(polyB[:, 0]))
        yA = max(np.min(polyA[:, 1]), np.min(polyB[:, 1]))
        xB = min(np.max(polyA[:, 0]), np.max(polyB[:, 0]))
        yB = min(np.max(polyA[:, 1]), np.max(polyB[:, 1]))

        interArea = max(0, xB - xA + 1) * max(0, yB - yA + 1)

        areaA = (np.max(polyA[:, 0]) - np.min(polyA[:, 0]) + 1) * (np.max(polyA[:, 1]) - np.min(polyA[:, 1]) + 1)
        areaB = (np.max(polyB[:, 0]) - np.min(polyB[:, 0]) + 1) * (np.max(polyB[:, 1]) - np.min(polyB[:, 1]) + 1)

        iou = interArea / float(areaA + areaB - interArea)
        return iou

    def process(self, input_path, output_path: Path, **kwargs):
        logger.info(f"Starting Temporal Processing for {input_path}")

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                mask_dir = temp_path / "masks"
                mask_dir.mkdir()

                # 1. Подготовка кадров
                frames_dir = None
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

                # 2. Основная логика: Детекция + Фильтрация + Маски
                self._process_frames_temporal(frames_dir, mask_dir)

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

    def _process_frames_temporal(self, frames_dir: Path, mask_dir: Path):
        """
        Главный конвейер временной фильтрации.
        """
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found")

        # ШАГ 1: Сканируем все кадры (RAW Detections)
        # Используем ОЧЕНЬ низкий порог (0.1), чтобы найти "НА" и всё остальное
        logger.info(f"Step 1: Raw OCR Scan on {len(frames)} frames...")
        raw_detections = []  # [ [bboxes_frame_0], [bboxes_frame_1], ... ]

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None:
                raw_detections.append([])
                continue

            # Используем CLAHE для улучшения
            enhanced_img = self._enhance_image_for_ocr(img)

            # Порог 0.1 - ловим ВСЁ (шум потом отфильтруем)
            bboxes = self.ocr.detect(enhanced_img, confidence_threshold=0.1)

            # Сохраняем только координаты (points)
            frame_boxes = [b['points'] for b in bboxes]
            raw_detections.append(frame_boxes)

        # ШАГ 2: Временная фильтрация
        # Текст должен присутствовать минимум на N кадрах подряд (или рядом)
        logger.info(f"Step 2: Temporal Filtering...")

        filtered_detections = [[] for _ in range(len(frames))]
        window_size = 2  # Смотрим на +/- 2 кадра (всего окно 5 кадров)

        for i in range(len(frames)):
            current_boxes = raw_detections[i]
            if not current_boxes: continue

            # Определяем диапазон соседей
            start_idx = max(0, i - window_size)
            end_idx = min(len(frames), i + window_size + 1)

            for box in current_boxes:
                consistency_count = 0

                # Проверяем соседей
                for j in range(start_idx, end_idx):
                    if i == j: continue  # Пропускаем себя

                    neighbor_boxes = raw_detections[j]
                    # Ищем совпадение в соседнем кадре
                    for n_box in neighbor_boxes:
                        iou = self._calculate_iou(box, n_box)
                        if iou > 0.3:  # Если боксы пересекаются хотя бы на 30%
                            consistency_count += 1
                            break  # Нашли совпадение в этом кадре, идем к следующему

                # КРИТЕРИЙ ИСТИНЫ:
                # Если бокс подтвержден хотя бы 1 соседом - считаем его текстом.
                # Глаза дергаются сильно, IoU будет низким или 0.
                if consistency_count >= 1:
                    filtered_detections[i].append(box)

        # ШАГ 3: Генерация Масок
        logger.info(f"Step 3: Generating Masks...")
        for i, frame_path in enumerate(frames):
            # Читаем размер для создания маски
            img = cv2.imread(str(frame_path))  # Просто чтобы узнать размер
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            valid_boxes = filtered_detections[i]

            # Если боксов нет - сохраняем черную маску
            if not valid_boxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            for box in valid_boxes:
                points = np.array(box, dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

            # ШАГ 4: Ядерное расширение (против фиолетового тумана)
            # Теперь мы можем безопасно расширять, т.к. глаз здесь уже нет
            kernel = np.ones((25, 25), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)

            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)

        logger.info(f"Processing complete. Masks generated.")


# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")