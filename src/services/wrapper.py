"""
Wrapper interface for backward compatibility with original API.
"""

import logging
import tempfile
import shutil
import time
from pathlib import Path
from typing import List, Optional

from src.core.config import get_config
from src.domain.models import ProcessingResult as PydanticProcessingResult
from src.domain.models import LegacyProcessingResult
from src.services.streaming_cleaner_service import StreamingSubtitleRemoverService

logger = logging.getLogger(__name__)


class SubtitleRemoverProPainterWrapper:
    """
    Wrapper for ProPainter subtitle removal processor implementing original interface.
    Provides backward compatibility with the old API.
    """
    
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        """
        Initialize ProPainter subtitle remover wrapper.
        
        Args:
            lang: Language for OCR ('en', 'ru', etc.)
            mask_dilation: Mask dilation radius in pixels
        """
        self._lang = lang
        self._mask_dilation = mask_dilation
        self._service: Optional[StreamingSubtitleRemoverService] = None
        self._logger = logging.getLogger(__name__)
        
        # Get configuration
        self._config = get_config()
        
        self._logger.info(f"SubtitleRemoverProPainterWrapper initialized (lang={lang}, dilation={mask_dilation})")
    
    def _get_service(self) -> StreamingSubtitleRemoverService:
        """Get or create the underlying service."""
        if self._service is None:
            self._service = StreamingSubtitleRemoverService(
                lang=self._lang,
                mask_dilation=self._mask_dilation,
                use_gpu=self._config.USE_GPU,
                use_gpu_for_ocr=self._config.USE_GPU_FOR_OCR,
                confidence_threshold=self._config.CONFIDENCE_THRESHOLD
            )
        return self._service
    
    def process(self, input_frames: List[Path], output_dir: Path, **options) -> LegacyProcessingResult:
        """
        Process frames to remove subtitles using ProPainter.
        Original interface for backward compatibility.
        
        Args:
            input_frames: List of input frame paths
            output_dir: Output directory for processed frames
            **options: Additional options (ignored for now)
            
        Returns:
            LegacyProcessingResult with success status
        """
        import time
        start_time = time.time()
        
        try:
            self._logger.info(f"Starting subtitle removal for {len(input_frames)} frames")
            
            # Get service
            service = self._get_service()
            
            # Create temporary input directory
            with tempfile.TemporaryDirectory(prefix="subs_input_") as tmp_input:
                tmp_input_path = Path(tmp_input)
                self._logger.info(f"Created temp directory: {tmp_input_path}")
                
                # Copy frames to temporary directory
                self._logger.info(f"Copying {len(input_frames)} frames to temp directory...")
                for frame in input_frames:
                    shutil.copy2(frame, tmp_input_path / frame.name)
                self._logger.info("Frames copied successfully")
                
                # Process frames using service
                result = service.process_frames_direct(input_frames, output_dir)
                
                # Convert Pydantic result to legacy format
                legacy_result = self._convert_to_legacy_result(result, start_time, len(input_frames))
                
                self._logger.info(f"Subtitle removal completed successfully")
                return legacy_result
                
        except Exception as e:
            self._logger.exception(f"ProPainter subtitle removal failed: {e}")
            duration = time.time() - start_time
            
            return LegacyProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=duration,
                errors=[str(e)]
            )
    
    def _convert_to_legacy_result(self, 
                                  pydantic_result: PydanticProcessingResult, 
                                  start_time: float,
                                  input_frame_count: int) -> LegacyProcessingResult:
        """Convert Pydantic ProcessingResult to LegacyProcessingResult."""
        duration = time.time() - start_time if 'time' in locals() else 0
        
        legacy_result = LegacyProcessingResult(
            success=pydantic_result.success,
            output_path=pydantic_result.output_path,
            frames_processed=pydantic_result.frames_processed,
            duration_seconds=duration,
            errors=pydantic_result.errors
        )
        
        # Add metrics
        if pydantic_result.stats:
            legacy_result.add_metric('frames_total', pydantic_result.stats.frames_total)
            legacy_result.add_metric('duration_seconds', pydantic_result.stats.duration_seconds)
            legacy_result.add_metric('device_used', pydantic_result.stats.device_used)
        
        legacy_result.add_metric('frames_processed', pydantic_result.frames_processed)
        legacy_result.add_metric('duration_per_frame', 
                                duration / input_frame_count if input_frame_count > 0 else 0)
        legacy_result.add_metric('processor', 'subtitle_remover_propainter')
        
        return legacy_result
    
    @classmethod
    def is_available(cls) -> bool:
        """Check if ProPainter subtitle remover is available."""
        try:
            # Check basic dependencies
            import cv2
            import torch
            import numpy as np
            from paddleocr import PaddleOCR  # noqa: F401
            
            # Check ProPainter via service
            service = StreamingSubtitleRemoverService()
            return service.is_available()
            
        except ImportError:
            return False
    
    def supports_gpu(self) -> bool:
        """Check if GPU is supported (ProPainter uses GPU if available)."""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False
    
    # Additional methods for direct access to new service
    
    def get_service(self) -> StreamingSubtitleRemoverService:
        """Get the underlying StreamingSubtitleRemoverService instance."""
        return self._get_service()
    
    def process_with_new_api(self, input_dir: Path, output_dir: Path) -> PydanticProcessingResult:
        """
        Process using the new API (InpaintingRequest).
        
        Args:
            input_dir: Input directory with frames
            output_dir: Output directory for processed frames
            
        Returns:
            Pydantic ProcessingResult
        """
        from src.domain.models import InpaintingRequest
        
        service = self._get_service()
        request = InpaintingRequest(input_dir=input_dir, output_dir=output_dir)
        return service.process(request)
