import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    FULL SPECTRUM DETECTOR.
    Combines 3 layers of detection to catch ANY type of subtitle:
    1. Saturation Mask (Colors on B&W background).
    2. Value Mask (Bright white/yellow text).
    3. Sobel Mask (Vertical edges/outlines).
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Full Spectrum Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            # 1. Конвертация в HSV для анализа цвета и света
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            s_channel = hsv[:, :, 1]
            v_channel = hsv[:, :, 2]

            # --- СЛОЙ 1: Насыщенность (Для манги/эдитов) ---
            # Ищем всё, что хоть немного цветное (S > 30)
            _, mask_sat = cv2.threshold(s_channel, 30, 255, cv2.THRESH_BINARY)

            # --- СЛОЙ 2: Яркость (Для обычных сабов) ---
            # Ищем всё очень яркое (V > 210)
            _, mask_val = cv2.threshold(v_channel, 210, 255, cv2.THRESH_BINARY)

            # --- СЛОЙ 3: Края (Для текста с обводкой) ---
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image

            # Ищем вертикальные линии (бока букв)
            sobel_x = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
            abs_sobel = cv2.convertScaleAbs(sobel_x)
            # Низкий порог, чтобы поймать даже тусклые границы
            _, mask_edges = cv2.threshold(abs_sobel, 30, 255, cv2.THRESH_BINARY)

            # --- ОБЪЕДИНЕНИЕ ---
            # Собираем всё вместе: Цвет ИЛИ Яркость ИЛИ Края
            combined = cv2.bitwise_or(mask_sat, mask_val)
            combined = cv2.bitwise_or(combined, mask_edges)

            # --- МОРФОЛОГИЯ (Склеивание) ---
            # Ядро (30, 5) - достаточно широкое для слов, достаточно высокое для жирного шрифта
            kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 5))
            connected = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_connect)

            # --- ФИЛЬТРАЦИЯ ---
            # Убираем только откровенный мусор (точки)
            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            mask = np.zeros_like(gray)

            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)

                # МИНИМАЛЬНЫЙ ФИЛЬТР:
                # Просто не точка (w>10, h>5).
                # Убрали проверку Aspect Ratio, чтобы не терять короткие слова.
                # Убрали верхний лимит, чтобы не терять огромный текст.
                if w > 10 and h > 5:
                    cv2.rectangle(mask, (x, y), (x + w, y + h), 255, -1)

            # --- ДИЛАТАЦИЯ ---
            if self.mask_dilation > 0:
                d_val = self.mask_dilation // 2
                k = cv2.getStructuringElement(cv2.MORPH_RECT, (d_val, d_val))
                final_mask = cv2.dilate(mask, k, iterations=1)
            else:
                final_mask = mask

            return final_mask

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def is_available(self) -> bool:
        return True