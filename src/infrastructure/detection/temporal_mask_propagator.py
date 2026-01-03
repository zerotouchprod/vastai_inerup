"""
Temporal Mask Propagator для propagation масок через кадры.
Использует keyframe strategy: OCR каждые N кадров, между ними - optical flow.

Version: 2.1.0
Date: January 3, 2026
"""

import numpy as np
import logging
from typing import List, Dict, Optional
from pathlib import Path

from .optical_flow_tracker import OpticalFlowTracker, FlowParameters

logger = logging.getLogger(__name__)


class TemporalMaskPropagator:
    """
    Пропагирует маски через кадры используя keyframe strategy.

    Strategy:
    1. Детектируем текст в ключевых кадрах (каждые N кадров)
    2. Между ключевыми кадрами - propagate маску с optical flow
    3. Temporal validation (reuse from v2.0)

    Performance gain:
    - Before: OCR every frame = 150ms × 150 = 22.5s
    - After: OCR every 5th = 150ms × 30 + Flow 50ms × 120 = 10.5s
    - Speedup: 2.1x faster!

    Example:
        propagator = TemporalMaskPropagator(keyframe_interval=5)
        masks = propagator.propagate_masks(frames, ocr_detector)
    """

    def __init__(self,
                 keyframe_interval: int = 5,
                 flow_parameters: Optional[FlowParameters] = None):
        """
        Initialize temporal mask propagator.

        Args:
            keyframe_interval: Интервал ключевых кадров (5 = OCR каждые 5 кадров)
            flow_parameters: Параметры optical flow (default: balanced)
        """
        self.keyframe_interval = keyframe_interval
        self.flow_tracker = OpticalFlowTracker(flow_parameters)

        logger.info(f"TemporalMaskPropagator initialized (keyframe_interval={keyframe_interval})")

    def propagate_masks(self,
                       frames: List[np.ndarray],
                       ocr_detector,
                       roi_str: str = 'bottom') -> Dict[int, np.ndarray]:
        """
        Генерирует маски для всех кадров используя propagation.

        Args:
            frames: Список кадров
            ocr_detector: OCR detector (должен иметь метод detect())
            roi_str: ROI string для OCR

        Returns:
            Dict mapping frame_idx -> mask (binary uint8)
        """
        if not frames:
            logger.warning("No frames provided to propagate_masks")
            return {}

        total_frames = len(frames)
        masks = {}

        logger.info(f"Propagating masks through {total_frames} frames (keyframe_interval={self.keyframe_interval})")

        # 1. Детектируем в ключевых кадрах
        keyframes = list(range(0, total_frames, self.keyframe_interval))
        ocr_count = 0

        for kf_idx in keyframes:
            # OCR детекция
            logger.debug(f"OCR detection on keyframe {kf_idx}/{total_frames}")
            detections = ocr_detector.detect(frames[kf_idx], roi_str=roi_str)

            # Создаем маску из детекций
            mask = self._create_mask_from_detections(frames[kf_idx], detections)
            masks[kf_idx] = mask
            ocr_count += 1

        logger.info(f"OCR performed on {ocr_count} keyframes (saved {total_frames - ocr_count} OCR calls)")

        # 2. Propagate между ключевыми кадрами
        flow_count = 0
        for i in range(total_frames):
            if i not in masks:
                # Warp из предыдущего кадра
                prev_frame = frames[i-1]
                curr_frame = frames[i]
                prev_mask = masks[i-1]

                warped_mask = self.flow_tracker.warp_mask(prev_frame, curr_frame, prev_mask)
                masks[i] = warped_mask
                flow_count += 1

                if flow_count % 20 == 0:
                    logger.debug(f"Flow propagation: {flow_count} frames processed")

        logger.info(f"Flow propagation performed on {flow_count} frames")

        # 3. Temporal validation (optional)
        # TODO: Apply temporal consistency validation from v2.0
        # validated_masks = self._apply_temporal_validation(masks)

        return masks

    def _create_mask_from_detections(self,
                                     frame: np.ndarray,
                                     detections: List[Dict]) -> np.ndarray:
        """
        Создает бинарную маску из OCR детекций.

        Args:
            frame: Frame для размера маски
            detections: Список детекций с ключом 'points'

        Returns:
            Binary mask (uint8, 0-255)
        """
        import cv2

        mask = np.zeros(frame.shape[:2], dtype=np.uint8)

        for det in detections:
            if 'points' in det:
                points = np.array(det['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

        return mask

    def _apply_temporal_validation(self, masks: Dict[int, np.ndarray]) -> Dict[int, np.ndarray]:
        """
        Применяет temporal consistency validation (reuse from v2.0).

        Voting filter: keep only pixels appearing in ≥2 frames within window.

        Args:
            masks: Dict of frame_idx -> mask

        Returns:
            Validated masks
        """
        if len(masks) < 3:
            return masks  # Нужно минимум 3 кадра для validation

        validated = {}
        window_size = 2  # ±2 frames window

        frame_indices = sorted(masks.keys())

        for i, frame_idx in enumerate(frame_indices):
            # Window bounds
            start_idx = max(0, i - window_size)
            end_idx = min(len(frame_indices), i + window_size + 1)

            # Frames в window
            window_frames = frame_indices[start_idx:end_idx]

            # Accumulate votes
            h, w = masks[frame_idx].shape
            pixel_votes = np.zeros((h, w), dtype=np.uint8)

            for wf_idx in window_frames:
                pixel_votes += (masks[wf_idx] > 0).astype(np.uint8)

            # Keep pixels with ≥2 votes
            validated_mask = ((pixel_votes >= 2).astype(np.uint8) * 255)
            validated[frame_idx] = validated_mask

        return validated

    def estimate_speedup(self, num_frames: int, ocr_time_ms: float = 150, flow_time_ms: float = 50) -> dict:
        """
        Оценивает speedup от использования keyframe strategy.

        Args:
            num_frames: Количество кадров
            ocr_time_ms: Время OCR на кадр (default: 150ms)
            flow_time_ms: Время flow на кадр (default: 50ms)

        Returns:
            Dict с метриками
        """
        keyframes = (num_frames + self.keyframe_interval - 1) // self.keyframe_interval
        flow_frames = num_frames - keyframes

        time_without_propagation = num_frames * ocr_time_ms
        time_with_propagation = (keyframes * ocr_time_ms) + (flow_frames * flow_time_ms)

        speedup = time_without_propagation / time_with_propagation

        return {
            'total_frames': num_frames,
            'keyframes': keyframes,
            'flow_frames': flow_frames,
            'time_without_ms': time_without_propagation,
            'time_with_ms': time_with_propagation,
            'speedup': speedup,
            'time_saved_ms': time_without_propagation - time_with_propagation
        }

