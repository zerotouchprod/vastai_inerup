"""
Animated Text Detector - главный координатор для детекции анимированных субтитров.
Объединяет optical flow, color detection, и temporal validation.

Version: 2.1.0
Date: January 3, 2026
"""

import numpy as np
import logging
from typing import List, Dict, Optional
from pathlib import Path

from .optical_flow_tracker import OpticalFlowTracker, FlowParameters
from .temporal_mask_propagator import TemporalMaskPropagator
from .color_change_detector import ColorChangeDetector

logger = logging.getLogger(__name__)


class AnimatedTextDetector:
    """
    Главный класс для детекции анимированных субтитров.

    Координирует:
    - Optical flow tracking (движение текста)
    - Temporal mask propagation (ускорение через keyframes)
    - Color change detection (караоке-эффект)
    - Temporal validation (from v2.0)

    Поддерживает:
    - Караоке-стиль (текст меняет цвет)
    - TikTok-стиль (текст движется)
    - Fade in/out эффекты
    - Bouncing/animated text

    Example:
        detector = AnimatedTextDetector(ocr_detector, roi_str='bottom')
        masks = detector.detect_animated_subtitles(frames)
        animation_type = detector.get_animation_type()
    """

    def __init__(self,
                 ocr_detector,
                 roi_str: str = 'bottom',
                 keyframe_interval: int = 5,
                 flow_parameters: Optional[FlowParameters] = None):
        """
        Initialize animated text detector.

        Args:
            ocr_detector: OCR detector (EasyOCR wrapper)
            roi_str: ROI string для ограничения области поиска
            keyframe_interval: Интервал ключевых кадров (5 = OCR каждые 5 кадров)
            flow_parameters: Параметры optical flow
        """
        self.ocr = ocr_detector
        self.roi_str = roi_str

        # Компоненты
        self.flow_tracker = OpticalFlowTracker(flow_parameters)
        self.mask_propagator = TemporalMaskPropagator(keyframe_interval, flow_parameters)
        self.color_detector = ColorChangeDetector()

        self._animation_type = None  # Detected animation type
        self._tracked_bboxes = {}    # Cached tracked bboxes

        logger.info(
            f"AnimatedTextDetector initialized "
            f"(roi={roi_str}, keyframe_interval={keyframe_interval})"
        )

    def detect_animated_subtitles(self, frames: List[np.ndarray]) -> Dict[int, np.ndarray]:
        """
        Главный метод детекции анимированных субтитров.

        Pipeline:
        1. Temporal mask propagation (OCR каждые N кадров)
        2. Optical flow tracking для уточнения
        3. Color change detection для караоке
        4. Temporal validation (reuse from v2.0)

        Args:
            frames: Список кадров (BGR numpy arrays)

        Returns:
            Dict mapping frame_idx -> binary mask
        """
        if not frames:
            logger.warning("No frames provided")
            return {}

        logger.info(f"Detecting animated text in {len(frames)} frames")

        # 1. Temporal mask propagation (основной метод)
        masks = self.mask_propagator.propagate_masks(frames, self.ocr, self.roi_str)

        logger.info(f"Generated {len(masks)} masks via temporal propagation")

        # 2. Optical flow tracking для анализа движения
        # Extract bboxes from first keyframe
        first_keyframe_idx = 0
        first_keyframe_detections = self.ocr.detect(frames[first_keyframe_idx], roi_str=self.roi_str)

        if first_keyframe_detections:
            initial_bboxes = self._extract_bboxes_from_detections(first_keyframe_detections)

            # Track через все кадры
            self._tracked_bboxes = self.flow_tracker.track_bboxes_sequence(frames, initial_bboxes)
            logger.info(f"Tracked {len(initial_bboxes)} regions through {len(frames)} frames")
        else:
            logger.warning("No text detected in first keyframe")
            self._tracked_bboxes = {}

        # 3. Color change detection (определяем тип анимации)
        if self._tracked_bboxes:
            self._animation_type = self.color_detector.classify_animation_type(
                frames, self._tracked_bboxes
            )
            logger.info(f"Animation type detected: {self._animation_type}")
        else:
            self._animation_type = 'static'

        # 4. TODO: Temporal validation (reuse from v2.0)
        # validated_masks = self._apply_temporal_validation(masks)

        return masks

    def get_animation_type(self) -> str:
        """
        Возвращает detected animation type.

        Returns:
            'static' | 'karaoke' | 'moving' | 'both' | None (if not detected yet)
        """
        return self._animation_type

    def get_tracked_bboxes(self) -> Dict[int, List]:
        """Возвращает tracked bounding boxes."""
        return self._tracked_bboxes

    def estimate_performance_gain(self, num_frames: int) -> dict:
        """
        Оценивает performance gain от использования animated detection.

        Args:
            num_frames: Количество кадров

        Returns:
            Dict с метриками производительности
        """
        return self.mask_propagator.estimate_speedup(num_frames)

    def _extract_bboxes_from_detections(self, detections: List[Dict]) -> List[tuple]:
        """
        Извлекает bounding boxes из OCR детекций.

        Args:
            detections: List of detection dicts with 'points' key

        Returns:
            List of (x, y, w, h) tuples
        """
        bboxes = []

        for det in detections:
            if 'points' not in det:
                continue

            points = np.array(det['points'])

            # Вычисляем bounding rectangle
            x_min = int(np.min(points[:, 0]))
            y_min = int(np.min(points[:, 1]))
            x_max = int(np.max(points[:, 0]))
            y_max = int(np.max(points[:, 1]))

            w = x_max - x_min
            h = y_max - y_min

            bboxes.append((x_min, y_min, w, h))

        return bboxes

    def visualize_tracking(self, frames: List[np.ndarray], output_path: Optional[Path] = None):
        """
        Визуализирует tracking для debugging.

        Args:
            frames: Список кадров
            output_path: Опциональный путь для сохранения видео
        """
        if not self._tracked_bboxes:
            logger.warning("No tracked bboxes to visualize")
            return

        import cv2

        vis_frames = []

        for frame_idx, bboxes in self._tracked_bboxes.items():
            if frame_idx >= len(frames):
                continue

            vis_frame = frames[frame_idx].copy()

            # Draw bboxes
            for bbox in bboxes:
                x, y, w, h = bbox
                cv2.rectangle(vis_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

            # Add frame number
            cv2.putText(vis_frame, f"Frame {frame_idx}", (10, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            # Add animation type
            if self._animation_type:
                cv2.putText(vis_frame, f"Type: {self._animation_type}", (10, 60),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            vis_frames.append(vis_frame)

        # Save to video if path provided
        if output_path and vis_frames:
            h, w = vis_frames[0].shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(str(output_path), fourcc, 24, (w, h))

            for frame in vis_frames:
                out.write(frame)

            out.release()
            logger.info(f"Visualization saved to {output_path}")

