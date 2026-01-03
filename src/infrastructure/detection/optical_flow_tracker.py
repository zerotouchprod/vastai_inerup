"""
Optical Flow Tracker для отслеживания движения текстовых регионов между кадрами.
Использует Farneback Dense Optical Flow (OpenCV) для propagation масок.

Version: 2.1.0
Date: January 3, 2026
"""

import cv2
import numpy as np
import logging
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FlowParameters:
    """Параметры для Farneback optical flow algorithm."""

    pyr_scale: float = 0.5      # Масштаб пирамиды (0.5 = каждый следующий уровень в 2 раза меньше)
    levels: int = 3             # Количество уровней пирамиды
    winsize: int = 15           # Размер окна усреднения (больше = более плавный flow)
    iterations: int = 3         # Количество итераций на каждом уровне
    poly_n: int = 5             # Размер окна для полиномиальной аппроксимации
    poly_sigma: float = 1.2     # Стандартное отклонение Гаусса для сглаживания

    @classmethod
    def fast_preset(cls):
        """Быстрый режим: меньше уровней, меньше итераций."""
        return cls(levels=2, iterations=2, winsize=10)

    @classmethod
    def accurate_preset(cls):
        """Точный режим: больше уровней, больше итераций."""
        return cls(levels=4, iterations=5, winsize=20)


class OpticalFlowTracker:
    """
    Отслеживает движение текстовых регионов между кадрами используя оптический поток.

    Поддерживает:
    - Dense optical flow (Farneback) - для всех пикселей
    - Tracking bounding boxes через последовательность кадров
    - Warp masks используя flow vectors

    Example:
        tracker = OpticalFlowTracker()

        # Отслеживаем bbox между двумя кадрами
        new_bbox = tracker.track_bbox(frame1, frame2, (x, y, w, h))

        # Деформируем маску
        warped_mask = tracker.warp_mask(frame1, frame2, mask)
    """

    def __init__(self, parameters: Optional[FlowParameters] = None, max_dimension: int = 1280):
        """
        Initialize optical flow tracker.

        Args:
            parameters: Flow parameters (default: balanced preset)
            max_dimension: Max width/height for flow computation (prevents OOM on 4K)
                          Frames larger than this will be downscaled. Default: 1280 (HD)
        """
        self.params = parameters or FlowParameters()
        self.max_dimension = max_dimension
        self._flow_cache = {}  # Cache для computed flows

        logger.info(
            f"OpticalFlowTracker initialized (levels={self.params.levels}, "
            f"winsize={self.params.winsize}, iterations={self.params.iterations}, "
            f"max_dimension={max_dimension}px)"
        )

    def _maybe_downscale(self, frame: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Downscale frame if resolution exceeds max_dimension.

        Architect Recommendation: "Downscaling снизит потребление памяти в 4-8 раз
        и ускорит расчет flow в 10 раз, при этом точности для 'пятна маски' будет достаточно."

        Examples:
            4K (3840x2160) → HD (1280x720) = 9.3x less memory, 8x faster
            1080p (1920x1080) → HD (1280x720) = 2.3x less memory, 2.3x faster

        Args:
            frame: Input frame (BGR or grayscale)

        Returns:
            Tuple of (scaled_frame, scale_factor)
                scale_factor = 1.0 if no scaling needed
                scale_factor < 1.0 if downscaled (e.g., 0.5 = half size)
        """
        h, w = frame.shape[:2]
        max_dim = max(h, w)

        if max_dim <= self.max_dimension:
            return frame, 1.0  # No scaling needed

        # Calculate scale factor
        scale = self.max_dimension / max_dim
        new_w = int(w * scale)
        new_h = int(h * scale)

        # Downscale using INTER_AREA (best for downsampling)
        scaled = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        logger.debug(
            f"Downscaled {w}x{h} → {new_w}x{new_h} for flow computation "
            f"(scale={scale:.2f}, memory savings: {1/scale**2:.1f}x)"
        )

        return scaled, scale

    def _upscale_flow(self, flow: np.ndarray, target_shape: Tuple[int, int], scale: float) -> np.ndarray:
        """
        Upscale flow map back to original resolution and adjust vectors.

        Args:
            flow: Flow map computed at lower resolution (H, W, 2)
            target_shape: Target (height, width)
            scale: Scale factor used for downscaling

        Returns:
            Upscaled flow map at target resolution
        """
        target_h, target_w = target_shape

        # Resize flow map to target resolution
        flow_upscaled = cv2.resize(flow, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        # Scale flow vectors by inverse of scale factor
        # If we downscaled by 0.5, a 10px movement in scaled space = 20px in original
        flow_upscaled = flow_upscaled / scale

        return flow_upscaled

    def compute_flow(self,
                     frame1: np.ndarray,
                     frame2: np.ndarray,
                     cache_key: Optional[str] = None) -> np.ndarray:
        """
        Вычисляет dense optical flow между двумя кадрами.

        Now with adaptive downscaling for memory optimization!

        Args:
            frame1: Предыдущий кадр (BGR или grayscale)
            frame2: Текущий кадр (BGR или grayscale)
            cache_key: Опциональный ключ для кэширования

        Returns:
            Flow map shape (H, W, 2) - векторы (dx, dy) для каждого пикселя
        """
        if cache_key and cache_key in self._flow_cache:
            return self._flow_cache[cache_key]

        # Store original shape for upscaling
        original_shape = frame1.shape[:2]

        # Adaptive downscaling (Architect recommendation for 4K support)
        frame1_scaled, scale1 = self._maybe_downscale(frame1)
        frame2_scaled, scale2 = self._maybe_downscale(frame2)

        # Convert to grayscale if needed
        gray1 = cv2.cvtColor(frame1_scaled, cv2.COLOR_BGR2GRAY) if len(frame1_scaled.shape) == 3 else frame1_scaled
        gray2 = cv2.cvtColor(frame2_scaled, cv2.COLOR_BGR2GRAY) if len(frame2_scaled.shape) == 3 else frame2_scaled

        # Compute flow using Farneback
        flow = cv2.calcOpticalFlowFarneback(
            prev=gray1,
            next=gray2,
            flow=None,
            pyr_scale=self.params.pyr_scale,
            levels=self.params.levels,
            winsize=self.params.winsize,
            iterations=self.params.iterations,
            poly_n=self.params.poly_n,
            poly_sigma=self.params.poly_sigma,
            flags=0
        )

        # Upscale flow if we downscaled
        if scale1 < 1.0:
            flow = self._upscale_flow(flow, original_shape, scale1)

        if cache_key:
            self._flow_cache[cache_key] = flow

        return flow

    def track_bbox(self,
                   frame1: np.ndarray,
                   frame2: np.ndarray,
                   bbox: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """
        Отслеживает bounding box между двумя кадрами.

        Args:
            frame1: Предыдущий кадр
            frame2: Текущий кадр
            bbox: Bounding box (x, y, w, h) в frame1

        Returns:
            Новый bbox (x, y, w, h) в frame2
        """
        x, y, w, h = bbox
        flow = self.compute_flow(frame1, frame2)

        # Extract flow в bbox region
        flow_region = flow[y:y+h, x:x+w]

        # Median более robust чем mean
        median_dx = np.median(flow_region[:, :, 0])
        median_dy = np.median(flow_region[:, :, 1])

        # New position с clip к границам
        new_x = int(np.clip(x + median_dx, 0, frame2.shape[1] - w))
        new_y = int(np.clip(y + median_dy, 0, frame2.shape[0] - h))

        return new_x, new_y, w, h

    def warp_mask(self,
                  frame1: np.ndarray,
                  frame2: np.ndarray,
                  mask: np.ndarray) -> np.ndarray:
        """
        Деформирует маску используя optical flow.

        Ключевой метод для temporal mask propagation.

        Args:
            frame1: Предыдущий кадр
            frame2: Текущий кадр
            mask: Маска из frame1 (binary, uint8)

        Returns:
            Warped mask для frame2
        """
        flow = self.compute_flow(frame1, frame2)

        # Create coordinate grids
        h, w = mask.shape[:2]
        grid_y, grid_x = np.mgrid[0:h, 0:w].astype(np.float32)

        # Apply flow vectors
        map_x = grid_x + flow[:, :, 0]
        map_y = grid_y + flow[:, :, 1]

        # Remap mask
        warped_mask = cv2.remap(
            mask,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0
        )

        # Binarize (remap создает grayscale)
        _, warped_mask = cv2.threshold(warped_mask, 127, 255, cv2.THRESH_BINARY)

        return warped_mask

    def compute_motion_magnitude(self, flow: np.ndarray) -> float:
        """
        Вычисляет среднюю magnitude движения.
        Полезно для adaptive keyframe selection.

        Args:
            flow: Flow map (H, W, 2)

        Returns:
            Mean motion magnitude (pixels)
        """
        magnitude = np.sqrt(flow[:, :, 0]**2 + flow[:, :, 1]**2)
        return float(np.mean(magnitude))

    def track_bboxes_sequence(self,
                              frames: List[np.ndarray],
                              initial_bboxes: List[Tuple[int, int, int, int]]) -> Dict[int, List[Tuple]]:
        """
        Отслеживает несколько bounding boxes через последовательность кадров.

        Args:
            frames: Список кадров
            initial_bboxes: Начальные bbox'ы в первом кадре

        Returns:
            Dict mapping frame_idx -> list of tracked bboxes
        """
        if not frames or not initial_bboxes:
            return {}

        tracks = {0: initial_bboxes}

        logger.info(f"Tracking {len(initial_bboxes)} regions through {len(frames)} frames")

        for i in range(1, len(frames)):
            prev_frame = frames[i-1]
            curr_frame = frames[i]
            prev_bboxes = tracks[i-1]

            curr_bboxes = []
            for bbox in prev_bboxes:
                # Track each bbox
                new_bbox = self.track_bbox(prev_frame, curr_frame, bbox)
                curr_bboxes.append(new_bbox)

            tracks[i] = curr_bboxes

            # Log progress every 10 frames
            if i % 10 == 0:
                logger.debug(f"Tracked frame {i}/{len(frames)}")

        return tracks

    def clear_cache(self):
        """Очищает cache computed flows."""
        self._flow_cache.clear()
        logger.debug("Flow cache cleared")
