"""
Watermark removal processor wrapper.
Uses static detection and ProPainter inpainting for persistent watermarks.
"""

import logging
import tempfile
import shutil
import time
import numpy as np
from pathlib import Path
from typing import List, Optional

from src.domain.protocols import IProcessor
from src.domain.models import ProcessingResult
from src.infrastructure.image_processing.geometry import resolve_multi_roi
from src.infrastructure.image_processing.watermark_detector import (
    create_persistent_mask, expand_watermark_mask, validate_watermark_regions
)
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

logger = logging.getLogger(__name__)


class WatermarkRemoverWrapper(IProcessor):
    """
    Watermark removal processor using static detection and ProPainter inpainting.

    Unlike subtitle removal which detects text per-frame, watermark removal:
    1. Detects persistent regions across multiple frames (static watermarks)
    2. Creates a single unified mask for all frames
    3. Applies ProPainter inpainting with the persistent mask
    """

    def __init__(self,
                 roi: str = 'top-right',
                 static_detection: bool = True,
                 persistence_threshold: float = 0.8,
                 expansion: int = 10,
                 use_color: bool = True):
        """
        Initialize watermark remover.

        Args:
            roi: ROI string (single or multi: "top-right,bottom-left")
            static_detection: Use static detection (True) or per-frame OCR (False)
            persistence_threshold: Ratio of frames a pixel must appear in (0.0-1.0)
            expansion: Mask expansion radius in pixels
            use_color: Use color-aware detection for colored watermarks (recommended)

        Raises:
            GPURequiredError: If GPU is not available (CPU processing too slow)
        """
        # CRITICAL: Watermark removal requires GPU for ProPainter inpainting
        # CPU processing would take hours instead of minutes
        from src.infrastructure.utils.gpu_utils import require_gpu
        require_gpu("watermark removal")

        self._roi = roi
        self._static_detection = static_detection
        self._persistence_threshold = persistence_threshold
        self._expansion = expansion
        self._use_color = use_color
        self._logger = logging.getLogger(__name__)

        self._logger.info(
            f"WatermarkRemoverWrapper initialized:"
        )
        self._logger.info(f"  ROI: {roi}")
        self._logger.info(f"  Static detection: {static_detection}")
        self._logger.info(f"  Persistence threshold: {persistence_threshold}")
        self._logger.info(f"  Expansion: {expansion}px")
        self._logger.info(f"  Color-aware: {use_color}")

    def process(self, input_frames: List[Path], output_dir: Path, **options) -> ProcessingResult:
        """
        Process frames to remove watermarks.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory for processed frames
            **options: Additional options

        Returns:
            ProcessingResult with success status
        """
        start_time = time.time()

        import cv2

        try:
            self._logger.info(f"=== Watermark Removal Started ===")
            self._logger.info(f"Total frames: {len(input_frames)}")
            self._logger.info(f"ROI: {self._roi}")

            # Get original dimensions for aspect ratio validation
            first_frame = cv2.imread(str(input_frames[0]))
            if first_frame is None:
                raise ValueError(f"Failed to read first frame: {input_frames[0]}")

            orig_height, orig_width = first_frame.shape[:2]
            orig_aspect = orig_width / orig_height

            self._logger.info(f"Original dimensions: {orig_width}x{orig_height} (aspect: {orig_aspect:.3f})")

            # Create work directory
            work_dir = output_dir.parent / "tmp_watermark_work"
            if work_dir.exists():
                shutil.rmtree(work_dir)
            work_dir.mkdir(parents=True)

            frames_dir = work_dir / "frames"
            masks_dir = work_dir / "masks"
            frames_dir.mkdir()
            masks_dir.mkdir()

            try:
                # Stage frames
                self._logger.info("Staging frames...")
                for i, src in enumerate(input_frames):
                    shutil.copy(src, frames_dir / f"{i:05d}.jpg")

                self._logger.info(f"✅ Staged {len(input_frames)} frames")

                # Generate persistent mask
                mask_coverage = 0.0  # Initialize default value
                if self._static_detection:
                    self._logger.info("=== Static Watermark Detection ===")
                    persistent_mask = self._generate_static_mask(input_frames)

                    mask_coverage = np.sum(persistent_mask > 0) / (persistent_mask.shape[0] * persistent_mask.shape[1])
                    self._logger.info(f"Mask coverage: {mask_coverage*100:.2f}% of frame")

                    # Save mask for all frames
                    self._logger.info(f"Replicating mask to {len(input_frames)} frames...")
                    for i in range(len(input_frames)):
                        mask_path = masks_dir / f"{i:05d}.jpg"
                        cv2.imwrite(str(mask_path), persistent_mask)

                    self._logger.info(f"✅ Masks prepared")
                else:
                    # Fallback to per-frame detection (like subtitles)
                    self._logger.warning("Static detection disabled, using per-frame OCR (slower)")
                    self._generate_perframe_masks(input_frames, masks_dir)

                # Run ProPainter inpainting
                self._logger.info("=== ProPainter Inpainting ===")
                inpainter = ProPainterAdapter()
                result_dir = inpainter.process(frames_dir, masks_dir, work_dir / "results")

                # Validate aspect ratio preservation
                results = sorted(list(result_dir.glob("*.jpg")) + list(result_dir.glob("*.png")))
                if results:
                    result_frame = cv2.imread(str(results[0]))
                    if result_frame is not None:
                        result_height, result_width = result_frame.shape[:2]
                        result_aspect = result_width / result_height
                        aspect_diff = abs(orig_aspect - result_aspect)

                        self._logger.info(f"=== Aspect Ratio Validation ===")
                        self._logger.info(f"  Original: {orig_width}x{orig_height} (ratio: {orig_aspect:.3f})")
                        self._logger.info(f"  Result:   {result_width}x{result_height} (ratio: {result_aspect:.3f})")
                        self._logger.info(f"  Difference: {aspect_diff:.4f}")

                        if aspect_diff > 0.05:
                            self._logger.warning(f"⚠️  Aspect ratio changed by {aspect_diff:.3f}!")
                            self._logger.warning(f"   ProPainter may have rotated the video")
                        else:
                            self._logger.info(f"✅ Aspect ratio preserved")

                # Copy results to output
                output_dir.mkdir(parents=True, exist_ok=True)

                for i, res_path in enumerate(results):
                    if i < len(input_frames):
                        target_name = input_frames[i].name
                        shutil.copy(res_path, output_dir / target_name)

                duration = time.time() - start_time
                self._logger.info(f"=== Watermark Removal Complete ===")
                self._logger.info(f"Duration: {duration:.1f}s")
                self._logger.info(f"Frames processed: {len(input_frames)}")
                self._logger.info(f"Output: {output_dir}")

                return ProcessingResult(
                    success=True,
                    output_path=output_dir,
                    frames_processed=len(input_frames),
                    duration_seconds=duration,
                    metrics={
                        'mode': 'watermark_removal',
                        'roi': self._roi,
                        'static_detection': self._static_detection,
                        'frames': len(input_frames),
                        'original_aspect': orig_aspect,
                        'mask_coverage': mask_coverage if self._static_detection else 0.0
                    }
                )

            finally:
                # Cleanup
                if work_dir.exists():
                    shutil.rmtree(work_dir)

        except Exception as e:
            self._logger.exception(f"Watermark removal failed: {e}")
            duration = time.time() - start_time

            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=duration,
                errors=[str(e)]
            )

    def _generate_static_mask(self, frame_paths: List[Path]) -> 'np.ndarray':
        """
        Generate persistent watermark mask using static detection.

        Args:
            frame_paths: List of frame paths

        Returns:
            Binary mask (numpy array)
        """
        import cv2
        import numpy as np

        # Load first frame to get dimensions
        first_frame = cv2.imread(str(frame_paths[0]))
        if first_frame is None:
            raise ValueError(f"Failed to read first frame: {frame_paths[0]}")

        h, w = first_frame.shape[:2]

        # Resolve ROI(s)
        roi_list = resolve_multi_roi(self._roi, w, h)
        self._logger.info(f"Detected {len(roi_list)} ROI zone(s): {self._roi}")
        for i, (x, y, rw, rh) in enumerate(roi_list):
            self._logger.info(f"  ROI {i+1}: ({x}, {y}, {rw}, {rh}) - {(rw*rh)/(w*h)*100:.1f}% of frame")

        # Create persistent mask with color-aware detection
        persistent_mask = create_persistent_mask(
            frame_paths,
            roi_list,
            self._persistence_threshold,
            use_color=self._use_color
        )

        # Validate and expand mask
        self._logger.info(f"Post-processing mask...")
        persistent_mask = validate_watermark_regions(persistent_mask)
        self._logger.info(f"Expanding mask by {self._expansion}px...")
        persistent_mask = expand_watermark_mask(persistent_mask, self._expansion)

        return persistent_mask

    def _generate_perframe_masks(self, frame_paths: List[Path], output_dir: Path):
        """
        Generate masks per-frame using OCR (fallback mode).

        Args:
            frame_paths: List of frame paths
            output_dir: Output directory for masks
        """
        from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
        import cv2
        import numpy as np

        ocr = PaddleWrapper(lang='en', use_gpu=True)

        for i, frame_path in enumerate(frame_paths):
            img = cv2.imread(str(frame_path))
            if img is None:
                continue

            # Detect text with ROI constraint
            bboxes = ocr.detect(img, confidence_threshold=0.01, roi_str=self._roi)

            # Create mask
            mask = np.zeros(img.shape[:2], dtype=np.uint8)
            for bbox in bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)

            # Expand mask
            if self._expansion > 0:
                kernel = np.ones((self._expansion, self._expansion), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)

            # Save mask
            mask_path = output_dir / f"{i:05d}.jpg"
            cv2.imwrite(str(mask_path), mask)

    @classmethod
    def is_available(cls) -> bool:
        """Check if watermark remover is available (requires ProPainter)."""
        try:
            from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
            adapter = ProPainterAdapter()
            return True
        except Exception:
            return False

    def supports_gpu(self) -> bool:
        """Check if GPU is supported."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

