"""
Main orchestration service for subtitle removal with ProPainter.
"""

import logging
import time
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import torch

from src.core.config import get_config
from src.core.device import get_device_manager
from src.core.exceptions import ProcessingError, ModelLoadingError
from src.domain.models import InpaintingRequest, ProcessingResult, ProcessingStats
from src.infrastructure.inpainting.propainter_loader import ProPainterLoader
from src.infrastructure.inpainting.propainter_adapter import ProPainterModelAdapter
from src.infrastructure.utils.video_utils import read_video, save_frames
from .mask_service import MaskGeneratorService

logger = logging.getLogger(__name__)


class SubtitleRemoverService:
    """Main service for subtitle removal orchestration."""
    
    def __init__(self,
                 lang: Optional[str] = None,
                 mask_dilation: Optional[int] = None,
                 use_gpu: Optional[bool] = None,
                 use_gpu_for_ocr: Optional[bool] = None,
                 confidence_threshold: Optional[float] = None):
        """
        Initialize subtitle remover service.
        
        Args:
            lang: Language for OCR (default from config)
            mask_dilation: Mask dilation radius (default from config)
            use_gpu: Use GPU for inpainting (default from config)
            use_gpu_for_ocr: Use GPU for OCR (default from config)
            confidence_threshold: Confidence threshold for text detection (default from config)
        """
        config = get_config()
        
        self.lang = lang or config.OCR_LANG
        self.mask_dilation = mask_dilation or config.MASK_DILATION
        self.use_gpu = use_gpu if use_gpu is not None else config.USE_GPU
        self.use_gpu_for_ocr = use_gpu_for_ocr if use_gpu_for_ocr is not None else config.USE_GPU_FOR_OCR
        self.confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # Initialize device manager
        force_cpu = not self.use_gpu
        self.device_manager = get_device_manager(force_cpu=force_cpu)
        self.device = self.device_manager.get_device()
        
        # Initialize services
        self.mask_service = MaskGeneratorService(
            lang=self.lang,
            mask_dilation=self.mask_dilation,
            use_gpu_for_ocr=self.use_gpu_for_ocr,
            confidence_threshold=self.confidence_threshold
        )
        
        # Initialize ProPainter components
        self.propainter_loader = ProPainterLoader()
        self.model_adapter = None
        self.model_loaded = False
        
        logger.info(f"SubtitleRemoverService initialized (lang={self.lang}, "
                   f"dilation={self.mask_dilation}, device={self.device})")
    
    def load_model(self) -> None:
        """Load ProPainter model if not already loaded."""
        if self.model_loaded and self.model_adapter is not None:
            return
        
        try:
            # Check if ProPainter is available
            if not self.propainter_loader.is_available():
                raise ModelLoadingError("ProPainter is not available (modules or weights missing)")
            
            # Load model
            model = self.propainter_loader.load_model(self.device)
            
            # Create adapter
            self.model_adapter = ProPainterModelAdapter(model, self.device)
            self.model_loaded = True
            
            logger.info("ProPainter model loaded successfully")
            
        except Exception as e:
            raise ModelLoadingError(f"Failed to load ProPainter model: {e}")
    
    def process(self, request: InpaintingRequest) -> ProcessingResult:
        """
        Process subtitle removal request.
        
        Args:
            request: Inpainting request with input and output directories
            
        Returns:
            Processing result with success status and statistics
        """
        start_time = time.time()
        errors = []
        
        try:
            logger.info(f"Starting subtitle removal: {request.input_dir} -> {request.output_dir}")
            
            # Load model
            self.load_model()
            
            # Step 1: Generate masks
            logger.info("Step 1/3: Generating masks...")
            temp_mask_dir = request.output_dir.parent / "tmp_masks_propainter"
            if temp_mask_dir.exists():
                shutil.rmtree(temp_mask_dir)
            
            mask_dir = self.mask_service.generate_masks(
                input_dir=request.input_dir,
                output_dir=temp_mask_dir,
                batch_size=get_config().BATCH_SIZE
            )
            
            # Step 2: Read video and masks
            logger.info("Step 2/3: Reading frames and masks...")
            video_frames, fps = read_video(str(request.input_dir))
            video_masks, _ = read_video(str(mask_dir), gray=True)
            
            # Prepare tensors
            video_frames_t = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
            video_masks_t = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
            
            # Step 3: Process frames in chunks
            logger.info("Step 3/3: Running AI inpainting (ProPainter)...")
            pred_frames = self._process_in_chunks(video_frames_t, video_masks_t)
            
            # Convert back to numpy and save
            pred_frames = pred_frames.permute(0, 2, 3, 1).cpu().numpy() * 255.0
            pred_frames = pred_frames.astype(np.uint8)
            
            # Save frames
            request.output_dir.mkdir(parents=True, exist_ok=True)
            save_frames(pred_frames, str(request.output_dir))
            
            # Cleanup
            self.mask_service.cleanup_temp_dir(temp_mask_dir)
            
            # Calculate statistics
            duration = time.time() - start_time
            stats = ProcessingStats(
                frames_total=len(pred_frames),
                duration_seconds=duration,
                device_used=str(self.device)
            )
            
            logger.info(f"Processing complete. Total time: {duration:.1f}s, "
                       f"Average speed: {len(pred_frames)/duration:.1f} FPS")
            
            return ProcessingResult(
                success=True,
                output_path=request.output_dir,
                frames_processed=len(pred_frames),
                errors=errors,
                stats=stats
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Subtitle removal failed: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            
            # Cleanup on error
            temp_mask_dir = request.output_dir.parent / "tmp_masks_propainter"
            self.mask_service.cleanup_temp_dir(temp_mask_dir)
            
            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                errors=errors,
                stats=ProcessingStats(
                    frames_total=0,
                    duration_seconds=duration,
                    device_used=str(self.device)
                )
            )
    
    def _process_in_chunks(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Process frames in chunks for memory efficiency.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        total_frames = frames.shape[0]
        
        # Estimate max batch size
        max_frames_per_chunk = self.device_manager.estimate_max_batch_size(
            frame_height=frames.shape[2],
            frame_width=frames.shape[3],
            model_memory_gb=2.0  # Estimated ProPainter memory usage
        )
        
        if total_frames <= max_frames_per_chunk:
            # Process all frames at once
            return self.model_adapter.process_chunk(frames, masks)
        
        # Process in chunks
        logger.info(f"Processing {total_frames} frames in chunks of {max_frames_per_chunk}")
        
        pred_chunks = []
        for chunk_start in range(0, total_frames, max_frames_per_chunk):
            chunk_end = min(chunk_start + max_frames_per_chunk, total_frames)
            logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_frames}")
            
            # Extract chunk
            frames_chunk = frames[chunk_start:chunk_end]
            masks_chunk = masks[chunk_start:chunk_end]
            
            # Process chunk
            pred_chunk = self.model_adapter.process_chunk(frames_chunk, masks_chunk)
            pred_chunks.append(pred_chunk.cpu())
            
            # Clear memory between chunks
            self.device_manager.empty_cache()
        
        # Combine chunks
        return torch.cat(pred_chunks, dim=0)
    
    def process_frames_direct(self, frame_paths: list[Path], output_dir: Path) -> ProcessingResult:
        """
        Process specific frame paths directly.
        
        Args:
            frame_paths: List of frame paths to process
            output_dir: Output directory for processed frames
            
        Returns:
            Processing result
        """
        start_time = time.time()
        errors = []
        
        try:
            logger.info(f"Processing {len(frame_paths)} frames directly")
            
            # Load model
            self.load_model()
            
            # Create temporary directories
            temp_input_dir = output_dir.parent / "tmp_input_frames"
            temp_mask_dir = output_dir.parent / "tmp_masks_direct"
            
            if temp_input_dir.exists():
                shutil.rmtree(temp_input_dir)
            if temp_mask_dir.exists():
                shutil.rmtree(temp_mask_dir)
            
            temp_input_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy frames to temporary directory
            for frame_path in frame_paths:
                shutil.copy2(frame_path, temp_input_dir / frame_path.name)
            
            # Create request
            request = InpaintingRequest(
                input_dir=temp_input_dir,
                output_dir=output_dir
            )
            
            # Process
            result = self.process(request)
            
            # Cleanup
            self.mask_service.cleanup_temp_dir(temp_input_dir)
            self.mask_service.cleanup_temp_dir(temp_mask_dir)
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Direct frame processing failed: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            
            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                errors=errors,
                stats=ProcessingStats(
                    frames_total=0,
                    duration_seconds=duration,
                    device_used=str(self.device)
                )
            )
    
    def is_available(self) -> bool:
        """Check if subtitle remover is available (ProPainter + OCR)."""
        try:
            # Check OCR
            import paddleocr  # noqa: F401
            
            # Check ProPainter
            return self.propainter_loader.is_available()
            
        except ImportError:
            return False
