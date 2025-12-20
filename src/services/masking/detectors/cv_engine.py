import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    PURPLE HUNTER ENGINE.
    Based on Debug Result #2 (Brightness) + Specific Hue Targeting.

    Strategy:
    1. TARGET 1: Purple/Pink Hue Range (110-170 in OpenCV HSV).
       This kills generic color noise.
    2. TARGET 2: Extreme Brightness (The white core of the letters).
    3. FILTER: Remove giant blobs (Manga page background).
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Purple Hunter Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            h, w = image.shape[:2]

            # --- ШАГ 1: ПОДГОТОВКА HSV ---
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

            # --- ШАГ 2: ЛОВИМ ФИОЛЕТОВЫЙ/РОЗОВЫЙ ---
            # OpenCV Hue range: 0-180
            # Фиолетовый ~125, Розовый ~160
            lower_purple = np.array([110, 50, 50])  # Hue 110+, Saturation 50+, Value 50+
            upper_purple = np.array([170, 255, 255])  # Hue 170 max

            mask_purple = cv2.inRange(hsv, lower_purple, upper_purple)

            # --- ШАГ 3: ЛОВИМ ЯРКУЮ СЕРДЦЕВИНУ БУКВ ---
            # Текст "светится". Берем пиксели ярче 240.
            # Но аккуратно: фон манги тоже может быть белым.
            v_channel = hsv[:, :, 2]
            _, mask_bright = cv2.threshold(v_channel, 240, 255, cv2.THRESH_BINARY)

            # Объединяем: Либо это фиолетовый ореол, либо белая сердцевина
            raw_mask = cv2.bitwise_or(mask_purple, mask_bright)

            # --- ШАГ 4: УМНАЯ ФИЛЬТРАЦИЯ (Ключевой момент) ---
            # Убираем фон страницы (гигантские куски) и шум (мелкие точки)

            # Сначала чистим мелкий шум
            open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            cleaned = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, open_kernel)

            # Склеиваем буквы
            close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
            connected = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, close_kernel)

            # Разбираем на части
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            final_mask = np.zeros((h, w), dtype=np.uint8)

            total_area = h * w

            for cnt in contours:
                area = cv2.contourArea(cnt)
                x, y, cw, ch = cv2.boundingRect(cnt)

                # ЛОГИКА ОТСЕВА:

                # 1. Если кусок больше 30% экрана — это ФОН СТРАНИЦЫ. Удаляем.
                if area > (total_area * 0.3):
                    continue

                    # 2. Если кусок микроскопический — это ШУМ. Удаляем.
                if cw < 10 or ch < 8:
                    continue

                # 3. Если кусок слишком высокий (вертикальная линия рамки манги)
                if ch > (cw * 3):
                    continue

                # Всё, что осталось — это текст
                cv2.drawContours(final_mask, [cnt], -1, 255, -1)

            # --- ШАГ 5: ФИНАЛЬНОЕ РАСШИРЕНИЕ ---
            if self.mask_dilation > 0:
                d = 6  # Умеренная дилатация
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (d, d))
                final_mask = cv2.dilate(final_mask, k, iterations=1)

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True