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
    def __init__(self, mask_service, inpainter):
        # inpainter передается из фабрики
        self.inpainter = inpainter
        # Используем GPU для OCR
        self.ocr = PaddleWrapper(lang='ru', use_gpu=True)
        # Указываем режим работы в логах
        logger.info(f"SubtitleRemoverService initialized (Mode: DOUBLE SCAN + CLAHE 4.0)")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        Улучшает контраст (CLAHE).
        Для "НА" критически важно поднять clipLimit до 4.0.
        """
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            # ИЗМЕНЕНИЕ 1: clipLimit 3.0 -> 4.0
            # Это максимально вытягивает "НА" из фона
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

                # --- 1. Подготовка кадров ---
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
                        logger.info(f"Extracting frames from video: {input_path}")
                        extractor.extract_frames(input_path, frames_dir)

                # --- 2. Генерация Масок (Double Scan) ---
                self._generate_binary_masks(frames_dir, mask_dir)

                # --- 3. Inpainting ---
                result_path = self.inpainter.process(frames_dir, mask_dir, output_path)

            class SimpleResult:
                def __init__(self, success=True, output_path=None):
                    self.success = success
                    self.output_path = output_path

            return SimpleResult(success=True, output_path=result_path)

        except Exception as e:
            logger.error(f"Subtitle removal failed: {e}")

            class SimpleResult:
                def __init__(self, success=False, output_path=None, errors=None):
                    self.success = success
                    self.output_path = output_path
                    self.errors = [str(e)] if errors is None else errors

            return SimpleResult(success=False, output_path=None, errors=[str(e)])

    def _generate_binary_masks(self, frames_dir: Path, mask_dir: Path):
        """
        Генерация масок.
        ИЗМЕНЕНИЕ 2: Стратегия "Double Scan" (Двойной проход).
        Мы ищем текст и на оригинале, и на улучшенной версии, и складываем результаты.
        Это не оставит "НА" шансов спрятаться.
        """
        logger.info(f"Generating binary masks (Double Scan strategy)...")

        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue

            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            # 1. Улучшаем копию (CLAHE 4.0 делает "НА" жирным)
            enhanced_img = self._enhance_image_for_ocr(img)

            # 2. Скан Улучшенной версии (Порог 0.2)
            bboxes_enhanced = self.ocr.detect(enhanced_img, confidence_threshold=0.2)

            # 3. Скан Оригинала (Порог 0.2) - на случай если CLAHE что-то исказил
            bboxes_orig = self.ocr.detect(img, confidence_threshold=0.2)

            # 4. ОБЪЕДИНЯЕМ РЕЗУЛЬТАТЫ
            all_bboxes = bboxes_enhanced + bboxes_orig

            if not all_bboxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # Рисуем все найденное
            for bbox in all_bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

            # 5. MEGA DILATION (Оставляем как было, раз это работает хорошо)
            # Kernel 20x20, 3 итерации
            kernel = np.ones((20, 20), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)

            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)

        logger.info(f"Generated {len(frames)} masks in {mask_dir}")