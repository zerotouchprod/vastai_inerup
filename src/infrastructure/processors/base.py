"""Base processor implementation using Template Method pattern."""

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any

from domain.models import ProcessingResult
from domain.exceptions import VideoProcessingError
from shared.logging import get_logger
from shared.metrics import MetricsCollector

logger = get_logger(__name__)


class BaseProcessor(ABC):
    """
    Abstract base class for all processors (upscalers, interpolators).

    Implements Template Method pattern:
    - Defines the skeleton of the processing algorithm
    - Delegates specific steps to subclasses
    - Handles common logic (validation, metrics, error handling)
    """

    def __init__(self, metrics: MetricsCollector = None):
        """
        Initialize base processor.

        Args:
            metrics: Optional metrics collector
        """
        self._logger = get_logger(self.__class__.__name__)
        self._metrics = metrics or MetricsCollector()

    def process(
        self,
        input_frames: List[Path],
        output_dir: Path,
        **options
    ) -> ProcessingResult:
        """
        Template method for processing frames.

        This method defines the overall algorithm structure.
        Subclasses implement specific steps.

        Args:
            input_frames: List of input frame paths
            output_dir: Directory for output frames
            **options: Processing options

        Returns:
            ProcessingResult with details

        Raises:
            VideoProcessingError: If processing fails
        """
        self._metrics.start_timer('total_processing')

        try:
            # Step 1: Validate inputs
            self._logger.info(f"Processing {len(input_frames)} frames")
            self._validate_inputs(input_frames, options)

            # Step 2: Prepare environment
            self._prepare_environment(output_dir)

            # Step 3: Execute processing (subclass-specific)
            self._metrics.start_timer('core_processing')
            output_frames = self._execute_processing(input_frames, output_dir, options)
            processing_time = self._metrics.stop_timer('core_processing')

            # Step 4: Validate outputs
            self._validate_outputs(output_frames)

            # Step 5: Build result
            total_time = self._metrics.stop_timer('total_processing')

            result = ProcessingResult(
                success=True,
                output_path=output_dir,
                frames_processed=len(output_frames),
                duration_seconds=total_time,
                metrics={
                    'processing_time': processing_time,
                    'total_time': total_time,
                    'fps': len(output_frames) / processing_time if processing_time > 0 else 0,
                    'overhead': total_time - processing_time,
                }
            )

            self._logger.info(
                f"Processing complete: {len(output_frames)} frames in {total_time:.2f}s "
                f"({result.metrics['fps']:.2f} fps)"
            )

            return result

        except Exception as e:
            self._logger.exception(f"Processing failed: {e}")

            # Build error result
            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=self._metrics.elapsed_time(),
                errors=[str(e)]
            )

    @abstractmethod
    def _execute_processing(
        self,
        input_frames: List[Path],
        output_dir: Path,
        options: Dict[str, Any]
    ) -> List[Path]:
        """
        Execute the actual processing (implemented by subclasses).

        Args:
            input_frames: Input frame paths
            output_dir: Output directory
            options: Processing options

        Returns:
            List of output frame paths

        Raises:
            VideoProcessingError: If processing fails
        """
        pass

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """
        Check if this processor is available in current environment.

        Returns:
            True if processor can be used
        """
        pass

    def _validate_inputs(self, frames: List[Path], options: Dict[str, Any]) -> None:
        """
        Validate input frames and options.

        Args:
            frames: Input frame paths
            options: Processing options

        Raises:
            VideoProcessingError: If validation fails
        """
        if not frames:
            raise VideoProcessingError("Input frames list is empty")

        for frame in frames:
            if not frame.exists():
                raise VideoProcessingError(f"Frame not found: {frame}")

    def _prepare_environment(self, output_dir: Path) -> None:
        """
        Prepare output directory and environment.

        Args:
            output_dir: Output directory path
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        self._logger.debug(f"Prepared output directory: {output_dir}")

    def _validate_outputs(self, output_frames: List[Path]) -> None:
        """
        Validate output frames.

        Args:
            output_frames: Output frame paths

        Raises:
            VideoProcessingError: If validation fails
        """
        if not output_frames:
            raise VideoProcessingError("No output frames generated")

        for frame in output_frames:
            if not frame.exists():
                raise VideoProcessingError(f"Output frame missing: {frame}")

    def supports_gpu(self) -> bool:
        """Check if GPU acceleration is available (default: False)."""
        return False

