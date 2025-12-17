"""Wrapper for subtitle removal processor."""

import logging
from pathlib import Path
from typing import List, Dict, Any

from domain.protocols import IProcessor
from domain.models import ProcessingResult
from .native import SubtitleRemoverNative

logger = logging.getLogger(__name__)


class SubtitleRemoverWrapper(IProcessor):
    """Wrapper for subtitle removal processor."""

    def __init__(self, lang: str = 'en', mask_dilation: int = 8, confidence_threshold: float = 0.3):
        """
        Initialize subtitle remover.

        Args:
            lang: Language for OCR ('en', 'ru', etc.)
            mask_dilation: Mask dilation radius in pixels
            confidence_threshold: Confidence threshold for text detection (0.0-1.0)
        """
        self._lang = lang
        self._mask_dilation = mask_dilation
        self._confidence_threshold = confidence_threshold
        self._processor = None
        self._logger = logging.getLogger(__name__)

    def process(self, input_frames: List[Path], output_dir: Path, **options) -> ProcessingResult:
        """
        Process frames to remove subtitles.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory for processed frames
            **options: Additional options (ignored for now)

        Returns:
            ProcessingResult with success status
        """
        import time
        start_time = time.time()

        try:
            # Create processor if not exists
            if self._processor is None:
                self._processor = SubtitleRemoverNative(
                    lang=self._lang,
                    mask_dilation=self._mask_dilation,
                    confidence_threshold=self._confidence_threshold
                )

            # Create temporary input directory
            import tempfile
            import shutil
            with tempfile.TemporaryDirectory(prefix="subs_input_") as tmp_input:
                tmp_input_path = Path(tmp_input)
                # Copy frames to temporary directory
                for frame in input_frames:
                    shutil.copy2(frame, tmp_input_path / frame.name)

                # Process frames
                self._processor.process_frames(tmp_input_path, output_dir)

            duration = time.time() - start_time

            # Count output frames
            output_frames = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
            
            return ProcessingResult(
                success=True,
                output_path=output_dir,
                frames_processed=len(output_frames),
                duration_seconds=duration,
                metrics={
                    'frames_processed': len(output_frames),
                    'duration_per_frame': duration / len(input_frames) if input_frames else 0,
                    'processor': 'subtitle_remover'
                }
            )

        except Exception as e:
            self._logger.exception(f"Subtitle removal failed: {e}")
            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=time.time() - start_time,
                errors=[str(e)]
            )

    @classmethod
    def is_available(cls) -> bool:
        """Check if subtitle remover is available."""
        try:
            import cv2
            import numpy as np
            from paddleocr import PaddleOCR  # noqa: F401
            return True
        except ImportError:
            return False

    def supports_gpu(self) -> bool:
        """Check if GPU is supported (currently CPU only)."""
        return False
