import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    COMPONENT-BASED DETECTOR.

    Problem: Manga pages are white. 'White text detector' selects the whole page (99% coverage).
    Solution: Don't panic globally. Filter individually.

    Logic:
    1. Detect Color (Saturation) + White (Brightness).
    2. Find Contours (Blobs).
    3. If a blob is GIANT (>10% of screen) -> It's background -> IGNORE.
    4. If a blob is Small/Medium -> It's text -> KEEP.
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Component Filter Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            h, w = image.shape[:2]
            total_area = h * w

            # --- 1. RAW DETECTION ---
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            s = hsv[:, :, 1]
            v = hsv[:, :, 2]

            # Цвет (Фиолетовый текст)
            _, mask_sat = cv2.threshold(s, 30, 255, cv2.THRESH_BINARY)

            # Белый (Текст или Фон страницы) - порог 245 (очень яркий)
            _, mask_white = cv2.threshold(v, 245, 255, cv2.THRESH_BINARY)

            # Объединяем
            raw_mask = cv2.bitwise_or(mask_sat, mask_white)

            # --- 2. CLEANING ---
            # Убираем шум (точки)
            open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            cleaned = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, open_kernel)

            # Склеиваем буквы в слова
            close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 5))
            connected = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)

            # --- 3. INTELLIGENT FILTERING ---
            # Вместо Panic Mode, разбираем каждый объект отдельно
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            final_mask = np.zeros((h, w), dtype=np.uint8)

            for cnt in contours:
                area = cv2.contourArea(cnt)
                x, y, cw, ch = cv2.boundingRect(cnt)

                # ЛОГИКА ФИЛЬТРА:

                # 1. Если это ОГРОМНЫЙ кусок (> 20% экрана) - это фон манги.
                if area > (total_area * 0.20):
                    continue  # Пропускаем (не рисуем)

                # 2. Если это МИКРОСКОПИЧЕСКИЙ кусок - это шум.
                if cw < 10 or ch < 8:
                    continue

                # 3. Всё остальное считаем текстом
                cv2.drawContours(final_mask, [cnt], -1, 255, -1)

            # --- 4. SAFETY DILATION ---
            if self.mask_dilation > 0:
                d = min(10, self.mask_dilation)
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (d, d))
                final_mask = cv2.dilate(final_mask, k, iterations=1)

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True