"""
Color Change Detector для детекции караоке-субтитров.
Анализирует изменение цвета в текстовых регионах (HSV histogram).

Version: 2.1.0
Date: January 3, 2026
"""

import cv2
import numpy as np
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)


class ColorChangeDetector:
    """
    Детектирует изменение цвета в текстовых регионах (караоке-эффект).

    Караоке-субтитры меняют цвет по мере пения:
    - Белый → Желтый → Зеленый
    - Или другие цветовые прогрессии

    Использует HSV histogram analysis для детекции вариации цвета.

    Example:
        detector = ColorChangeDetector()
        animation_type = detector.classify_animation_type(frames, tracked_bboxes)
        # Returns: 'static', 'karaoke', 'moving', or 'both'
    """

    def __init__(self,
                 color_threshold: float = 50.0,
                 motion_threshold: float = 5.0):
        """
        Initialize color change detector.

        Args:
            color_threshold: Порог для детекции цветоизменения (std of hue histogram)
            motion_threshold: Порог для детекции движения (pixels)
        """
        self.color_threshold = color_threshold
        self.motion_threshold = motion_threshold

        logger.info(
            f"ColorChangeDetector initialized "
            f"(color_threshold={color_threshold}, motion_threshold={motion_threshold})"
        )

    def detect_color_variance(self,
                             frames: List[np.ndarray],
                             tracked_bboxes: Dict[int, List[Tuple[int, int, int, int]]]) -> Dict[int, List[float]]:
        """
        Детектирует степень изменения цвета в каждом регионе.

        Args:
            frames: Список кадров
            tracked_bboxes: Dict mapping frame_idx -> list of bboxes

        Returns:
            Dict mapping frame_idx -> list of color_variance scores
        """
        color_variance = {}

        for frame_idx, bboxes in tracked_bboxes.items():
            if frame_idx >= len(frames):
                continue

            frame = frames[frame_idx]
            variances = []

            for bbox in bboxes:
                x, y, w, h = bbox

                # Безопасная экстракция региона
                x = max(0, min(x, frame.shape[1] - 1))
                y = max(0, min(y, frame.shape[0] - 1))
                w = max(1, min(w, frame.shape[1] - x))
                h = max(1, min(h, frame.shape[0] - y))

                region = frame[y:y+h, x:x+w]

                if region.size == 0:
                    variances.append(0.0)
                    continue

                # Преобразуем в HSV
                hsv_region = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)

                # Вычисляем histogram Hue канала (цветовой тон)
                hist = cv2.calcHist([hsv_region], [0], None, [180], [0, 180])

                # Стандартное отклонение = мера вариации
                variance = float(np.std(hist))
                variances.append(variance)

            color_variance[frame_idx] = variances

        return color_variance

    def compute_motion_magnitude(self,
                                tracked_bboxes: Dict[int, List[Tuple[int, int, int, int]]]) -> Dict[int, List[float]]:
        """
        Вычисляет magnitude движения для каждого bbox.

        Args:
            tracked_bboxes: Dict mapping frame_idx -> list of bboxes

        Returns:
            Dict mapping frame_idx -> list of motion magnitudes
        """
        motion_magnitude = {}

        frame_indices = sorted(tracked_bboxes.keys())

        for i in range(1, len(frame_indices)):
            prev_idx = frame_indices[i-1]
            curr_idx = frame_indices[i]

            prev_bboxes = tracked_bboxes[prev_idx]
            curr_bboxes = tracked_bboxes[curr_idx]

            magnitudes = []

            # Предполагаем что количество bboxes одинаково
            for prev_bbox, curr_bbox in zip(prev_bboxes, curr_bboxes):
                px, py, pw, ph = prev_bbox
                cx, cy, cw, ch = curr_bbox

                # Вычисляем displacement центра
                prev_center_x = px + pw / 2
                prev_center_y = py + ph / 2
                curr_center_x = cx + cw / 2
                curr_center_y = cy + ch / 2

                dx = curr_center_x - prev_center_x
                dy = curr_center_y - prev_center_y

                magnitude = float(np.sqrt(dx**2 + dy**2))
                magnitudes.append(magnitude)

            motion_magnitude[curr_idx] = magnitudes

        # Первый кадр - нет движения
        if frame_indices:
            motion_magnitude[frame_indices[0]] = [0.0] * len(tracked_bboxes[frame_indices[0]])

        return motion_magnitude

    def classify_animation_type(self,
                               frames: List[np.ndarray],
                               tracked_bboxes: Dict[int, List[Tuple[int, int, int, int]]]) -> str:
        """
        Классифицирует тип анимации текста.

        Args:
            frames: Список кадров
            tracked_bboxes: Tracked bounding boxes

        Returns:
            'static' | 'karaoke' | 'moving' | 'both'
        """
        if not tracked_bboxes:
            return 'static'

        # Вычисляем цветовую вариацию
        color_variance = self.detect_color_variance(frames, tracked_bboxes)

        # Вычисляем movement magnitude
        motion_magnitude = self.compute_motion_magnitude(tracked_bboxes)

        # Средние значения
        avg_color_var = self._compute_average(color_variance)
        avg_motion = self._compute_average(motion_magnitude)

        logger.info(
            f"Animation classification: avg_color_var={avg_color_var:.2f}, "
            f"avg_motion={avg_motion:.2f}px"
        )

        # Классификация
        has_color_change = avg_color_var > self.color_threshold
        has_motion = avg_motion > self.motion_threshold

        if has_color_change and has_motion:
            return 'both'  # И цвет меняется, и движется
        elif has_color_change:
            return 'karaoke'  # Только цвет меняется
        elif has_motion:
            return 'moving'  # Только движется
        else:
            return 'static'  # Статичный текст

    def _compute_average(self, data: Dict[int, List[float]]) -> float:
        """Вычисляет среднее по всем значениям в dict."""
        all_values = []
        for values in data.values():
            all_values.extend(values)

        return float(np.mean(all_values)) if all_values else 0.0

    def analyze_color_progression(self,
                                 frames: List[np.ndarray],
                                 bbox: Tuple[int, int, int, int],
                                 sample_rate: int = 5) -> List[Tuple[int, int, int]]:
        """
        Анализирует прогрессию цвета в bbox через кадры.

        Полезно для визуализации караоке-эффекта.

        Args:
            frames: Список кадров
            bbox: Bounding box для анализа
            sample_rate: Анализировать каждый N-й кадр

        Returns:
            List of dominant colors (BGR tuples) по кадрам
        """
        x, y, w, h = bbox
        colors = []

        for i in range(0, len(frames), sample_rate):
            frame = frames[i]

            # Extract region
            region = frame[y:y+h, x:x+w]

            if region.size == 0:
                colors.append((0, 0, 0))
                continue

            # Вычисляем dominant color (mean)
            mean_color = cv2.mean(region)[:3]  # BGR
            colors.append(tuple(int(c) for c in mean_color))

        return colors

