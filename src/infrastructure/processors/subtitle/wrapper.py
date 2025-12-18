"""Wrapper for subtitle removal processor using refactored architecture."""

import logging
from pathlib import Path
from typing import List, Dict, Any

from src.domain.protocols import IProcessor
from src.domain.models import ProcessingResult
from src.services.wrapper import SubtitleRemoverProPainterWrapper

logger = logging.getLogger(__name__)


class SubtitleRemoverWrapper(IProcessor):
    """Wrapper for subtitle removal processor using new refactored architecture."""

    def __init__(self, lang: str = 'en', mask_dilation: int = 12, confidence_threshold: float = 0.3):
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
        Process frames to remove subtitles using refactored ProPainter architecture.

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
            self._logger.info(f"Starting subtitle removal for {len(input_frames)} frames using refactored architecture")
            
            # Create processor if not exists
            if self._processor is None:
                self._logger.info(f"Creating SubtitleRemoverProPainterWrapper (lang={self._lang}, dilation={self._mask_dilation})")
                self._processor = SubtitleRemoverProPainterWrapper(
                    lang=self._lang,
                    mask_dilation=self._mask_dilation
                )
                self._logger.info("SubtitleRemoverProPainterWrapper created successfully")

            # Process frames using the new wrapper
            result = self._processor.process(input_frames, output_dir, **options)
            
            duration = time.time() - start_time
            self._logger.info(f"Subtitle removal completed in {duration:.1f} seconds")
            
            # Convert legacy result to ProcessingResult if needed
            if hasattr(result, 'to_pydantic'):
                # This is LegacyProcessingResult, convert to ProcessingResult
                pydantic_result = result.to_pydantic()
                return ProcessingResult(
                    success=pydantic_result.success,
                    output_path=pydantic_result.output_path,
                    frames_processed=pydantic_result.frames_processed,
                    duration_seconds=duration,
                    metrics={
                        'frames_processed': pydantic_result.frames_processed,
                        'duration_per_frame': duration / len(input_frames) if input_frames else 0,
                        'processor': 'subtitle_remover_propainter_refactored',
                        'device_used': pydantic_result.stats.device_used if pydantic_result.stats else 'unknown'
                    },
                    errors=pydantic_result.errors
                )
            else:
                # Already a ProcessingResult
                return result

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
        return SubtitleRemoverProPainterWrapper.is_available()

    def supports_gpu(self) -> bool:
        """Check if GPU is supported (ProPainter uses GPU if available)."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
