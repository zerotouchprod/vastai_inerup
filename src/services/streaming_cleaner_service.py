"""
Streaming subtitle removal service with memory optimization.
Processes frames one by one or in small batches to minimize memory usage.
"""

import logging
import time
import shutil
from pathlib import Path
from typing import Optional, List, Generator
import gc

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


class StreamingSubtitleRemoverService:
    """Streaming service for subtitle removal with minimal memory usage."""
    
    def __init__(self,
                 lang: Optional[str] = None,
                 mask_dilation: Optional[int] = None,
                 use_gpu: Optional[bool] = None,
                 use_gpu_for_ocr: Optional[bool] = None,
                 confidence_threshold: Optional[float] = None):
        """
        Initialize streaming subtitle remover service.
        
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
        
        logger.info(f"StreamingSubtitleRemoverService initialized (lang={self.lang}, "
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
        Process subtitle removal request with streaming approach.
        
        Args:
            request: Inpainting request with input and output directories
            
        Returns:
            Processing result with success status and statistics
        """
        start_time = time.time()
        errors = []
        
        try:
            logger.info(f"Starting streaming subtitle removal: {request.input_dir} -> {request.output_dir}")
            
            # Load model
            self.load_model()
            
            # Step 1: Generate masks (streaming)
            logger.info("Step 1/3: Generating masks...")
            temp_mask_dir = request.output_dir.parent / "tmp_masks_streaming"
            if temp_mask_dir.exists():
                shutil.rmtree(temp_mask_dir)
            
            mask_dir = self.mask_service.generate_masks(
                input_dir=request.input_dir,
                output_dir=temp_mask_dir,
                batch_size=2  # Very small batch size for memory efficiency
            )
            
            # Step 2: Process frames in streaming mode
            logger.info("Step 2/3: Processing frames in streaming mode...")
            request.output_dir.mkdir(parents=True, exist_ok=True)
            
            # Get frame and mask paths
            frame_paths = sorted(list(request.input_dir.glob("*.png")) + 
                                list(request.input_dir.glob("*.jpg")))
            mask_paths = sorted(list(mask_dir.glob("*.png")) + 
                               list(mask_dir.glob("*.jpg")))
            
            if len(frame_paths) != len(mask_paths):
                raise ProcessingError(f"Frame count mismatch: {len(frame_paths)} frames vs {len(mask_paths)} masks")
            
            # Process in micro-batches (1-2 frames at a time)
            processed_count = 0
            micro_batch_size = 1  # Process 1 frame at a time for minimal memory
            
            for i in range(0, len(frame_paths), micro_batch_size):
                batch_end = min(i + micro_batch_size, len(frame_paths))
                batch_frames = frame_paths[i:batch_end]
                batch_masks = mask_paths[i:batch_end]
                
                # Load batch
                frames_batch = []
                masks_batch = []
                
                for frame_path, mask_path in zip(batch_frames, batch_masks):
                    frame = cv2.imread(str(frame_path))
                    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                    
                    if frame is None or mask is None:
                        logger.warning(f"Failed to load frame or mask: {frame_path}, {mask_path}")
                        continue
                    
                    frames_batch.append(frame)
                    masks_batch.append(mask)
                
                if not frames_batch:
                    continue
                
                # Convert to tensors
                frames_t = torch.from_numpy(np.array(frames_batch)).permute(0, 3, 1, 2).float() / 255.0
                masks_t = torch.from_numpy(np.array(masks_batch)).unsqueeze(1).float() / 255.0
                
                # Move to device
                frames_t = frames_t.to(self.device)
                masks_t = masks_t.to(self.device)
                
                # Process batch
                with torch.no_grad():
                    pred_batch = self.model_adapter.process_chunk(frames_t, masks_t)
                
                # Convert back to numpy and save
                pred_batch = pred_batch.permute(0, 2, 3, 1).cpu().numpy() * 255.0
                pred_batch = pred_batch.astype(np.uint8)
                
                # Save processed frames
                for j, frame_path in enumerate(batch_frames):
                    output_path = request.output_dir / frame_path.name
                    cv2.imwrite(str(output_path), pred_batch[j])
                
                processed_count += len(batch_frames)
                
                # Log progress
                if processed_count % 10 == 0 or processed_count == len(frame_paths):
                    logger.info(f"Processed {processed_count}/{len(frame_paths)} frames")
                
                # Clear memory
                del frames_t, masks_t, pred_batch
                self.device_manager.empty_cache()
                gc.collect()
            
            # Cleanup
            self.mask_service.cleanup_temp_dir(temp_mask_dir)
            
            # Calculate statistics
            duration = time.time() - start_time
            stats = ProcessingStats(
                frames_total=processed_count,
                duration_seconds=duration,
                device_used=str(self.device)
            )
            
            logger.info(f"Streaming processing complete. Total time: {duration:.1f}s, "
                       f"Average speed: {processed_count/duration:.1f} FPS")
            
            return ProcessingResult(
                success=True,
                output_path=request.output_dir,
                frames_processed=processed_count,
                errors=errors,
                stats=stats
            )
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Streaming subtitle removal failed: {e}"
            logger.error(error_msg, exc_info=True)
            errors.append(error_msg)
            
            # Cleanup on error
            temp_mask_dir = request.output_dir.parent / "tmp_masks_streaming"
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
    
    def _stream_frames_and_masks(self, frame_dir: Path, mask_dir: Path) -> Generator:
        """Stream frames and masks one by one."""
        frame_paths = sorted(list(frame_dir.glob("*.png")) + 
                            list(frame_dir.glob("*.jpg")))
        mask_paths = sorted(list(mask_dir.glob("*.png")) + 
                           list(mask_dir.glob("*.jpg")))
        
        for frame_path, mask_path in zip(frame_paths, mask_paths):
            frame = cv2.imread(str(frame_path))
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            
            if frame is not None and mask is not None:
                yield frame_path.name, frame, mask
    
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
            
            # Create temporary input directory
            temp_input_dir = output_dir.parent / "tmp_input_frames_streaming"
            temp_mask_dir = output_dir.parent / "tmp_masks_streaming_direct"
            
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
