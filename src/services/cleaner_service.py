import tempfile
import shutil
import cv2
import numpy as np
from pathlib import Path
from src.shared.logging import get_logger

# Подключаем адаптеры
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

logger = get_logger(__name__)


class SubtitleRemoverService:
    """
    Final Production Service.
    FIXES SPECIFICALLY:
    1. "НА" text (low contrast): Fixed via CLAHE (Contrast Limited Adaptive Histogram Equalization).
    2. Green Boxes: Removed (debug drawing disabled).
    3. False Positives (Eyes): Threshold increased to 0.4.
    4. Purple Soap: Max dilation enabled.
    """

    def __init__(self, mask_service, inpainter):
        self.inpainter = inpainter
        # Инициализируем OCR на GPU
        self.ocr = PaddleWrapper(lang='ru', use_gpu=True)
        logger.info(f"SubtitleRemoverService initialized (Mode: FINAL PRODUCTION)")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        Критически важная функция для текста типа "НА".
        Вытягивает контраст локально, делая невидимые буквы видимыми.
        """
        try:
            # Переводим в LAB (L - яркость)
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)

            # Применяем агрессивный CLAHE к каналу яркости
            # clipLimit=4.0 — это очень сильно, специально для скрытого текста
            clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)

            # Собираем обратно
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

                # --- 1. Копируем кадры ---
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

                # --- 2. Генерируем маски (CLAHE включен) ---
                self._generate_binary_masks(frames_dir, mask_dir)

                # --- 3. Запускаем Inpainting ---
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

    def _generate_binary_masks(self, frames_dir: Path, mask_dir: Path):
        logger.info(f"Generating binary masks for frames in {frames_dir}")

        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue

            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            # А. Улучшаем копию для OCR (чтобы поймать "НА")
            enhanced_img = self._enhance_image_for_ocr(img)

            # Б. Детекция на УЛУЧШЕННОМ изображении
            # threshold=0.4 - игнорируем глаза, но CLAHE сделает "НА" достаточно контрастным,
            # чтобы уверенность была выше 0.4
            bboxes = self.ocr.detect(enhanced_img, confidence_threshold=0.4)

            # Фолбэк на оригинал (если CLAHE вдруг испортил что-то другое)
            if not bboxes:
                bboxes = self.ocr.detect(img, confidence_threshold=0.4)

            if not bboxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # В. Рисуем на МАСКЕ
            for bbox in bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

            # Г. MEGA DILATION
            # Расширяем зону удаления, чтобы убрать свечение
            kernel = np.ones((20, 20), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=3)

            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)

        logger.info(f"Generated {len(frames)} masks")


# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")