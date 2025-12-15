import logging
import cv2
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path
# Try-except import to allow running even if paddle is missing (optional safety)
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

# Настройка логирования Paddle, чтобы не спамил в консоль
if PaddleOCR:
    logging.getLogger("ppocr").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class SubtitleRemoverNative:
    """
    Удаляет вшитые субтитры используя PaddleOCR для детекции 
    и OpenCV Telea/NS для инпейнтинга (закрашивания).
    Работает на CPU, совместим с PyTorch Nightly билдами.
    """

    def __init__(self, lang: str = 'en', mask_dilation: int = 5):
        """
        :param lang: Язык субтитров ('en', 'ru' и т.д.)
        :param mask_dilation: На сколько пикселей расширять маску вокруг текста.
                              Больше = лучше убирает края, но мылит фон.
        """
        if PaddleOCR is None:
            raise ImportError("PaddleOCR not installed. Cannot remove subtitles.")
            
        self.lang = lang
        self.mask_dilation = mask_dilation
        logger.info(f"Initializing SubtitleRemoverNative (lang={lang}, CPU)...")
        # use_angle_cls=False faster, use_gpu=False required for this env
        self.ocr = PaddleOCR(use_angle_cls=False, lang=lang, use_gpu=False, show_log=False)
        logger.info("PaddleOCR initialized successfully.")

    def process_frames(self, input_dir: Path, output_dir: Path) -> None:
        """
        Обрабатывает все изображения в input_dir и сохраняет в output_dir.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Получаем список файлов (png/jpg)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        total = len(frames)

        logger.info(f"Starting subtitle removal on {total} frames...")

        for idx, frame_path in enumerate(frames):
            try:
                self._process_single_frame(frame_path, output_dir / frame_path.name)

                if idx % 10 == 0:
                    logger.info(f"Processed {idx}/{total} frames...")
            except Exception as e:
                logger.error(f"Failed to process frame {frame_path}: {e}")
                # В случае ошибки просто копируем оригинал, чтобы не ломать видео
                import shutil
                shutil.copy(frame_path, output_dir / frame_path.name)

    def _process_single_frame(self, input_path: Path, output_path: Path) -> None:
        # 1. Загрузка изображения
        img = cv2.imread(str(input_path))
        if img is None:
            raise ValueError(f"Could not read image: {input_path}")

        # 2. Детекция текста (PaddleOCR)
        # result структура: [[[[x1,y1], [x2,y2], ...], ("text", conf)], ...]
        result = self.ocr.ocr(img, cls=False)

        # Если текст не найден, result может быть None или пустым списком
        if not result or result[0] is None:
            # Текста нет, сохраняем оригинал
            cv2.imwrite(str(output_path), img)
            return

        # 3. Создание маски
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        boxes_found = False

        for line in result[0]:
            coords = line[0]  # Список координат полигона [[x,y], [x,y], [x,y], [x,y]]
            conf = line[1][1]  # Уверенность (confidence)

            # Фильтруем мусор
            if conf > 0.5:
                points = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [points], 255)
                boxes_found = True

        if not boxes_found:
            cv2.imwrite(str(output_path), img)
            return

        # 4. Расширение маски (Dilation)
        # Это нужно, чтобы убрать артефакты сжатия вокруг букв
        kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=1)

        # 5. Inpainting (Закрашивание)
        # cv2.INPAINT_TELEA или cv2.INPAINT_NS. Telea обычно быстрее и дает меньше артефактов на тексте.
        result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

        # 6. Сохранение
        cv2.imwrite(str(output_path), result_img)
