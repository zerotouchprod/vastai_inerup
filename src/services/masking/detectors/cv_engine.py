import logging
import cv2
import numpy as np
from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    UNIVERSAL TEXTURE DETECTOR (Morphological Gradient).
    Reliable backup for OCR. Works on contrast, not specific colors.
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Texture Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image

            # 1. Morphological Gradient (Выделяет любые резкие границы)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)

            # 2. Бинаризация (Otsu - сам находит порог)
            _, binary = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

            # 3. Склеивание (Горизонтальное)
            # Ядро (25, 3) - объединяет буквы в слова
            morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
            connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, morph_kernel)

            # 4. Фильтрация мусора
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            mask = np.zeros_like(gray)

            h, w = gray.shape

            for cnt in contours:
                x, y, cw, ch = cv2.boundingRect(cnt)
                aspect_ratio = cw / float(ch)

                # Фильтр: Широкое (AR>1.5), не точка (w>15), не фон (h < 40% экрана)
                if (cw > 15 and ch > 8 and aspect_ratio > 1.5 and ch < (h * 0.4)):
                    cv2.rectangle(mask, (x, y), (x + cw, y + ch), 255, -1)

            # 5. Дилатация (Расширение)
            if self.mask_dilation > 0:
                dk = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                final_mask = cv2.dilate(mask, dk, iterations=1)
            else:
                final_mask = mask

            return final_mask

        except Exception as e:
            logger.error(f"CV Error: {e}")
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True