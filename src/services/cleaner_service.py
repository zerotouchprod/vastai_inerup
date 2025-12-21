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
    Final Calibrated Service (Stabilized v2).

    Adjustments based on feedback:
    1. Threshold -> 0.25: Stops detecting mouths/chins as text.
    2. Window Radius -> 1: Reduces "smearing" of false positives over time.
    3. Dilation -> (20,20)x3: Still removes glow, but slightly more precise boundaries.
    """

    def __init__(self, mask_service, inpainter, lang='ru'):
        self.inpainter = inpainter

        if isinstance(lang, str):
            langs = [l.strip() for l in lang.split(',')]
        else:
            langs = lang if isinstance(lang, list) else ['en']
        if 'en' not in langs: langs.append('en')

        self.ocr_langs = langs
        # Используем GPU
        self.ocr = PaddleWrapper(lang=self.ocr_langs, use_gpu=True)
        logger.info(f"SubtitleRemoverService initialized (Mode: STABILIZED v2)")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """CLAHE: Делает текст контрастным."""
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            # ClipLimit 4.0 - агрессивный контраст для "НА"
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return final
        except Exception:
            return img

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

                # 2. Генерация Стабилизированных Масок
                self._generate_stabilized_masks(frames_dir, mask_dir)

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

    def _generate_stabilized_masks(self, frames_dir: Path, mask_dir: Path):
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        num_frames = len(frames)
        if num_frames == 0:
            raise ValueError(f"No frames found")

        logger.info(f"Step 1: Detecting text on all {num_frames} frames...")

        all_detections = []

        # Проход 1: Сбор данных
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None:
                all_detections.append([])
                continue

            # CLAHE
            enhanced_img = self._enhance_image_for_ocr(img)

            # CORRECTION 1: Threshold 0.25
            # Достаточно низко для "НА" (с CLAHE), но достаточно высоко, чтобы игнорировать рот.
            bboxes = self.ocr.detect(enhanced_img, confidence_threshold=0.25)

            frame_boxes = [b['points'] for b in bboxes]
            all_detections.append(frame_boxes)

        logger.info(f"Step 2: Rendering stabilized masks...")

        # CORRECTION 2: Window Radius 1 (Prev, Curr, Next)
        # Меньше "размазывания" ошибок во времени
        window_radius = 1

        for i, frame_path in enumerate(frames):
            img = cv2.imread(str(frame_path))
            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            start_idx = max(0, i - window_radius)
            end_idx = min(num_frames, i + window_radius + 1)

            boxes_in_window = []
            for j in range(start_idx, end_idx):
                boxes_in_window.extend(all_detections[j])

            if not boxes_in_window:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # Рисуем накопленные боксы
            for box in boxes_in_window:
                points = np.array(box, dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

            # CORRECTION 3: Dilation (20,20) x 3
            # Чуть аккуратнее чем (25,25), но все еще очень мощно против свечения
            kernel = np.ones((20, 20), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)

            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)

        logger.info(f"Stabilized masks generated.")


# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")