import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    BALANCED PURPLE HUNTER.
    Adjusted for anime/manga subtitles with glow/outlines.

    Changes vs Surgical Mode:
    1. Wider Hue Range: Catches more purple variations (105-175).
    2. Lower Brightness Threshold: Catches text that isn't pure white (V > 230).
    3. Stronger Connection: Connects letters into solid word blocks.
    4. Moderate Dilation (8px): Ensures glowing edges are covered by the mask.
    """

    def __init__(self, mask_dilation: int = 15):
        # Используем среднюю дилатацию. 8 пикселей достаточно для обводки.
        self.mask_dilation = 8
        logger.info(f"CV Engine initialized (Balanced Mode, dilation={self.mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            h, w = image.shape[:2]
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # --- 1. ЦВЕТ (Фиолетовый/Розовый) ---
            # Расширили диапазон Hue (с 115 до 105)
            # Добавили минимальную насыщенность (S > 40), чтобы не ловить серый шум
            lower_purple = np.array([105, 40, 40])
            upper_purple = np.array([175, 255, 255])
            mask_purple = cv2.inRange(hsv, lower_purple, upper_purple)

            # --- 2. ЯРКОСТЬ (Сердцевина букв) ---
            # Понизили порог с 245 до 230, чтобы ловить "почти белый"
            v_channel = hsv[:, :, 2]
            _, mask_bright = cv2.threshold(v_channel, 230, 255, cv2.THRESH_BINARY)

            # Объединяем
            raw_mask = cv2.bitwise_or(mask_purple, mask_bright)

            # --- 3. МОРФОЛОГИЯ (Склеивание) ---
            # Чистим шум
            open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            cleaned = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, open_kernel)

            # Склеиваем сильнее: Ядро (20, 5) объединит буквы в сплошной блок
            close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
            connected = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)

            # --- 4. ФИЛЬТРАЦИЯ ---
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            final_mask = np.zeros((h, w), dtype=np.uint8)
            total_area = h * w

            for cnt in contours:
                area = cv2.contourArea(cnt)
                x, y, cw, ch = cv2.boundingRect(cnt)

                # Отсекаем гигантские куски фона (> 20% экрана)
                if area > (total_area * 0.20): continue
                # Отсекаем совсем мелочь
                if cw < 10 or ch < 10: continue

                cv2.drawContours(final_mask, [cnt], -1, 255, -1)

            # --- 5. ДИЛАТАЦИЯ (Расширение) ---
            # Умеренное расширение, чтобы закрыть свечение вокруг букв
            d = self.mask_dilation
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
            final_mask = cv2.dilate(final_mask, k, iterations=1)

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True