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
    Final Balanced Service.
    1. PROTECTS EYES: Uses high confidence (0.35) for standard detection.
    2. CATCHES 'НА': Uses CLAHE enhancement specifically to find faint/short text.
    3. REMOVES FOG: Uses MASSIVE dilation (30px kernel) to delete glow/shadows completely.
    """

    def __init__(self, mask_service, inpainter, lang='ru'):
        self.inpainter = inpainter

        # Динамическая обработка языков из конфига
        if isinstance(lang, str):
            langs = [l.strip() for l in lang.split(',')]
        else:
            langs = lang if isinstance(lang, list) else ['en']

        # Всегда добавляем английский, это улучшает работу модели
        if 'en' not in langs:
            langs.append('en')

        self.ocr_langs = langs
        self.ocr = PaddleWrapper(lang=self.ocr_langs, use_gpu=True)
        logger.info(f"SubtitleRemoverService initialized. Langs: {self.ocr_langs}")

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        CLAHE (Contrast Limited Adaptive Histogram Equalization).
        Делает "НА" видимым для нейросети.
        """
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            # ClipLimit 4.0 - агрессивный контраст
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

                # --- 1. Подготовка кадров ---
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

                # --- 2. Генерация Масок ---
                self._generate_binary_masks(frames_dir, mask_dir)

                # --- 3. Inpainting ---
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
        logger.info(f"Generating binary masks...")

        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")

        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue

            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            # --- ПРОХОД 1: Безопасный (Оригинал) ---
            # Порог 0.35: Хорошо видит "РОДИЛСЯ", игнорирует глаза.
            bboxes_standard = self.ocr.detect(img, confidence_threshold=0.35)

            # --- ПРОХОД 2: Снайперский (Улучшенный контраст) ---
            # Только здесь мы можем увидеть "НА".
            # Порог 0.25: Достаточно низкий для текста, но на контрастном фото глаза выглядят иначе.
            enhanced_img = self._enhance_image_for_ocr(img)
            bboxes_enhanced = self.ocr.detect(enhanced_img, confidence_threshold=0.25)

            # Объ