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
            self._logger.info(f"Starting subtitle removal for {len(input_frames)} frames")
            
            # Create processor if not exists
            if self._processor is None:
                self._logger.info(f"Creating SubtitleRemoverNative (lang={self._lang}, dilation={self._mask_dilation})")
                self._processor = SubtitleRemoverNative(
                    lang=self._lang,
                    mask_dilation=self._mask_dilation,
                    confidence_threshold=self._confidence_threshold
                )
                self._logger.info("SubtitleRemoverNative created successfully")

            # Create temporary input directory
            import tempfile
            import shutil
            with tempfile.TemporaryDirectory(prefix="subs_input_") as tmp_input:
                tmp_input_path = Path(tmp_input)
                self._logger.info(f"Created temp directory: {tmp_input_path}")
                
                # Copy frames to temporary directory
                self._logger.info(f"Copying {len(input_frames)} frames to temp directory...")
                for frame in input_frames:
                    shutil.copy2(frame, tmp_input_path / frame.name)
                self._logger.info("Frames copied successfully")

                # Process frames
                self._logger.info("Starting frame processing with SubtitleRemoverNative...")
                self._processor.process_frames(tmp_input_path, output_dir)
                self._logger.info("Frame processing completed")

            duration = time.time() - start_time
            self._logger.info(f"Subtitle removal completed in {duration:.1f} seconds")

            # Count output frames
            output_frames = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
            self._logger.info(f"Found {len(output_frames)} output frames in {output_dir}")
            
            if output_frames:
                self._logger.info(f"First 3 output files: {[f.name for f in output_frames[:3]]}")
            
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
            # Try to see what's in the output directory
            try:
                if output_dir.exists():
                    files = list(output_dir.iterdir())
                    self._logger.error(f"Output directory contains {len(files)} files after error")
                    if files:
                        self._logger.error(f"First 5 files: {[f.name for f in files[:5]]}")
            except Exception as dir_err:
                self._logger.error(f"Could not check output directory: {dir_err}")
                
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
