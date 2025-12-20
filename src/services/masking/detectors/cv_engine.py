import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    SURGICAL COLOR DETECTOR with SAFETY VALVE.

    Logic:
    1. Look ONLY for Color Saturation (Manga is B&W, Text is Colored).
    2. Look ONLY for High Brightness (White text).
    3. IGNORE EDGES (Sobel), because Manga art creates false positives.
    4. SAFETY VALVE: If mask > 40% of screen, reject it (Subtitles never take 40% of screen).
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Surgical Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            h, w = image.shape[:2]
            total_pixels = h * w

            # --- ШАГ 1: Поиск по насыщенности (для фиолетового текста) ---
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            s_channel = hsv[:, :, 1]
            v_channel = hsv[:, :, 2]

            # Порог насыщенности 40 (отсекает шум сжатия, но ловит цвет)
            _, mask_sat = cv2.threshold(s_channel, 40, 255, cv2.THRESH_BINARY)

            # --- ШАГ 2: Поиск по яркости (для чисто белого текста) ---
            # Очень высокий порог (230), чтобы не цеплять светло-серый фон манги
            _, mask_val = cv2.threshold(v_channel, 230, 255, cv2.THRESH_BINARY)

            # Объединяем
            raw_mask = cv2.bitwise_or(mask_sat, mask_val)

            # --- ШАГ 3: Чистка шума (Opening) ---
            # Убираем одинокие пиксели
            open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            cleaned = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, open_kernel)

            # --- ШАГ 4: Аккуратное склеивание ---
            # Не используем гигантские ядра! Только чтобы склеить буквы внутри слова.
            # (20, 5) - достаточно, чтобы П Р О Б У Д И Л А стало одним блоком, но не слиплось с фоном
            connect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5))
            connected = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, connect_kernel)

            # --- ШАГ 5: ПРЕДОХРАНИТЕЛЬ (SAFETY VALVE) ---
            white_pixels = cv2.countNonZero(connected)
            coverage = white_pixels / total_pixels

            if coverage > 0.4:  # Если маска занимает больше 40% области
                logger.warning(
                    f"Panic: Mask covers {coverage:.1%} of ROI. Assuming false positive (Manga background). Resetting.")
                # Аварийный режим: возвращаем пустую маску (лучше не удалить ничего, чем удалить всё видео)
                # Или можно попробовать вернуть только mask_sat без морфологии, но безопаснее вернуть 0.
                return np.zeros((h, w), dtype=np.uint8)

            # --- ШАГ 6: Финальная дилатация ---
            if self.mask_dilation > 0:
                d_val = min(10, self.mask_dilation)  # Ограничиваем дилатацию
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (d_val, d_val))
                final_mask = cv2.dilate(connected, k, iterations=1)
            else:
                final_mask = connected

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True