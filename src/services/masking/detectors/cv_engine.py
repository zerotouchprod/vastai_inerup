import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    UNIVERSAL TEXTURE DETECTOR.
    Does not rely on specific colors. Relies on contrast and geometry.
    Pipeline:
    1. LAB Color Space (L-channel) -> CLAHE (Boost local contrast).
    2. Canny Edge Detection (Find all high-contrast edges).
    3. Morphological Closing (Connect edges horizontally into "blobs").
    4. Geometric Filtering (Keep only blobs shaped like subtitles).
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        # Минимальная ширина и высота для фильтрации шума
        self.min_text_w = 20
        self.min_text_h = 8
        # Минимальное соотношение сторон (ширина/высота), чтобы считать это строкой
        self.min_aspect_ratio = 1.5
        logger.info(f"CV Engine initialized (Universal Texture Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            h, w = image.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)

            # 1. Улучшение контраста (LAB -> L-channel -> CLAHE)
            # Это позволяет находить текст и в темных, и в ярких зонах одновременно.
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l_channel, _, _ = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(l_channel)

            # 2. Canny Edge Detection (Поиск границ)
            # Пороги 30/90 позволяют ловить даже слабые границы текста.
            edges = cv2.Canny(enhanced, 30, 90)

            # 3. Морфологическое Закрытие (Склеивание)
            # Ядро широкое (25) и низкое (3).
            # Цель: объединить буквы в слова, но не объединять разные строки между собой.
            kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
            closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel_connect)

            # 4. Геометрическая Фильтрация
            contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in contours:
                x, y, cw, ch = cv2.boundingRect(cnt)
                aspect_ratio = cw / float(ch) if ch > 0 else 0

                # Критерии субтитра:
                # - Достаточно широкий (AR > 1.5)
                # - Не шум (cw > 20, ch > 8)
                # - Не слишком высокий (не стена, не столб) - меньше 40% высоты экрана
                if (aspect_ratio > self.min_aspect_ratio and
                        cw > self.min_text_w and
                        ch > self.min_text_h and
                        ch < (h * 0.4)):
                    # Рисуем белый прямоугольник на маске
                    cv2.rectangle(mask, (x, y), (x + cw, y + ch), 255, -1)

            # 5. Финальная дилатация (Safety Buffer)
            # Немного расширяем маску, чтобы гарантированно закрыть края букв.
            if self.mask_dilation > 0:
                # Используем половину от заданной дилатации, чтобы не быть слишком агрессивными
                d_val = max(3, self.mask_dilation // 2)
                kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (d_val, d_val))
                final_mask = cv2.dilate(mask, kernel_dilate, iterations=1)
            else:
                final_mask = mask

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            # В случае ошибки возвращаем пустую маску, а не весь экран
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True