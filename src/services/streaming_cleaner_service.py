import logging
import time
import shutil
import sys
from pathlib import Path
from typing import Optional, List, Generator
import gc

import cv2
import numpy as np
import torch

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    tqdm = None
    TQDM_AVAILABLE = False

from src.core.config import get_config
from src.core.device import get_device_manager
from src.core.exceptions import ProcessingError, ModelLoadingError
from src.domain.models import InpaintingRequest, ProcessingResult, ProcessingStats
from src.infrastructure.inpainting.propainter_loader import ProPainterLoader
from src.infrastructure.inpainting.propainter_adapter import ProPainterModelAdapter
from src.infrastructure.utils.video_utils import read_video, save_frames
from src.infrastructure.image_processing import tensor_ops
from src.infrastructure.debugging.visualizer import MaskVisualizer
from src.services.strategies.dynamic_tiling import DynamicTilingStrategy
from .mask_service import MaskGeneratorService

logger = logging.getLogger(__name__)


class StreamingSubtitleRemoverService:
    """Streaming service for subtitle removal with minimal memory usage."""
    
    def __init__(self,
                 lang: Optional[str] = None,
                 mask_dilation: Optional[int] = None,
                 use_gpu: Optional[bool] = None,
                 use_gpu_for_ocr: Optional[bool] = None,
                 confidence_threshold: Optional[float] = None,
                 debug_masks: bool = False):
        """
        Initialize streaming subtitle remover service.
        
        Args:
            lang: Language for OCR (default from config)
            mask_dilation: Mask dilation radius (default from config)
            use_gpu: Use GPU for inpainting (default from config)
            use_gpu_for_ocr: Use GPU for OCR (default from config)
            confidence_threshold: Confidence threshold for text detection (default from config)
            debug_masks: Enable debug mask saving (default False)
        """
        config = get_config()
        
        self.lang = lang or config.OCR_LANG
        self.mask_dilation = mask_dilation or config.MASK_DILATION
        self.use_gpu = use_gpu if use_gpu is not None else config.USE_GPU
        self.use_gpu_for_ocr = use_gpu_for_ocr if use_gpu_for_ocr is not None else config.USE_GPU_FOR_OCR
        self.confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        self.debug_masks = debug_masks
        
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
        
        # CPU fallback state
        self.cpu_fallback_active = False
        
        # Downscaling state
        self.downscaled = False
        self.target_height = config.MAX_HEIGHT  # target height for downscaling
        self.scale_factor = 1.0
        self.auto_downscale = config.AUTO_DOWNSCALE
        
        # ROI state
        self.use_roi_optimization = config.USE_ROI_OPTIMIZATION
        self.roi_height_ratio = config.ROI_HEIGHT_RATIO
        self.roi_zone_height_ratio = config.ROI_ZONE_HEIGHT_RATIO
        
        # Dynamic cropping settings
        self.padding_px = config.PADDING_PX
        self.max_crop_area_ratio = config.MAX_CROP_AREA_RATIO
        
        # Initialize strategy
        self.strategy = DynamicTilingStrategy(config)
        
        # Initialize debug visualizer
        self.visualizer = MaskVisualizer(Path("."), enabled=self.debug_masks)
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
    
    def _enable_cpu_fallback(self) -> None:
        """
        Enable CPU fallback mode by moving model to CPU and updating device.
        """
        if self.cpu_fallback_active:
            return
        
        logger.warning("GPU failed even at batch_size=1. Switching to CPU Fallback Mode.")
        
        # Move model to CPU
        cpu_device = torch.device("cpu")
        self.model_adapter.to_device(cpu_device)
        
        # Update service device
        self.device = cpu_device
        self.cpu_fallback_active = True
        
        # Clear GPU cache
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        logger.info("CPU fallback activated. Processing will continue on CPU.")
    
    def _downscale_frames(self, frames: torch.Tensor, masks: torch.Tensor, target_height: int = 720):
        """
        Downscale frames and masks to target height while maintaining aspect ratio.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            target_height: Target height in pixels
            
        Returns:
            Tuple of (downscaled_frames, downscaled_masks, scale_factor)
        """
        return tensor_ops.downscale_batch(frames, masks, target_height)
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
    
    def process(self, request: InpaintingRequest) -> ProcessingResult:
        """
        Main pipeline orchestrator: loads model, generates masks, processes frames in chunks.
        """
        start_time = time.time()
        errors = []
        try:
            # 1. Setup
            logger.info(f"Starting pipeline: {request.input_dir.name}")
            self.load_model()

            # 2. Masks
            temp_mask_dir = request.output_dir.parent / "tmp_masks"
            mask_dir = self.mask_service.generate_masks(request.input_dir, temp_mask_dir)

            # 3. Prepare I/O
            frame_paths = sorted(list(request.input_dir.glob("*.png")) + list(request.input_dir.glob("*.jpg")))
            mask_paths = sorted(list(mask_dir.glob("*.png")) + list(mask_dir.glob("*.jpg")))

            # Ensure output directory exists
            request.output_dir.mkdir(parents=True, exist_ok=True)

            # 4. Streaming Loop
            batch_size = 5  # Start optimistic
            chunk_start = 0
            total_frames = len(frame_paths)

            while chunk_start < total_frames:
                chunk_end = min(chunk_start + batch_size, total_frames)
                logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_frames}")

                # Load frames and masks
                frames = []
                masks = []
                for i in range(chunk_start, chunk_end):
                    frame = cv2.imread(str(frame_paths[i]))
                    mask = cv2.imread(str(mask_paths[i]), cv2.IMREAD_GRAYSCALE)
                    if frame is None or mask is None:
                        raise ProcessingError(f"Failed to load frame or mask: {frame_paths[i]}, {mask_paths[i]}")
                    frames.append(frame)
                    masks.append(mask)

                # Convert to tensors
                frames_t = torch.stack([torch.from_numpy(f).permute(2, 0, 1).float() / 255.0 for f in frames])
                masks_t = torch.stack([torch.from_numpy(m).unsqueeze(0).float() / 255.0 for m in masks])
                frames_t = frames_t.to(self.device)
                masks_t = masks_t.to(self.device)

                # DELEGATION TO STRATEGY with OOM recovery
                try:
                    processed_t = self._process_chunk_with_oom_recovery(frames_t, masks_t, batch_size)
                except Exception as e:
                    logger.error(f"Chunk processing failed: {e}")
                    errors.append(f"Chunk {chunk_start}-{chunk_end}: {e}")
                    # Continue to next chunk
                    chunk_start = chunk_end
                    continue

                # Save processed frames
                for i, pred_t in enumerate(processed_t):
                    pred = pred_t.permute(1, 2, 0).cpu().numpy() * 255.0
                    pred = pred.astype(np.uint8)
                    output_path = request.output_dir / frame_paths[chunk_start + i].name
                    cv2.imwrite(str(output_path), pred)

                # Cleanup
                del frames, masks, frames_t, masks_t, processed_t
                self.device_manager.empty_cache()
                gc.collect()

                chunk_start = chunk_end

            # Cleanup temporary mask directory
            if temp_mask_dir.exists():
                shutil.rmtree(temp_mask_dir)

            duration = time.time() - start_time
            logger.info(f"Pipeline completed successfully in {duration:.2f}s")
            return ProcessingResult(
                success=True,
                output_path=request.output_dir,
                frames_processed=total_frames,
                errors=errors,
                stats=ProcessingStats(
                    frames_total=total_frames,
                    duration_seconds=duration,
                    device_used=str(self.device)
                )
            )

        except Exception as e:
            duration = time.time() - start_time
            error_msg = f"Critical failure: {e}"
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
    
    def _process_chunk_with_oom_recovery(self, frames: torch.Tensor, masks: torch.Tensor, initial_batch_size: int) -> torch.Tensor:
        """
        Process a chunk of frames with OOM recovery.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            initial_batch_size: Initial batch size to try
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        current_batch_size = initial_batch_size
        original_frames = frames
        original_masks = masks
        
        # Determine if ROI should be attempted (high resolution and ROI enabled)
        use_roi = (
            self.use_roi_optimization and 
            original_frames.shape[2] > self.target_height and
            not self.downscaled
        )
        
        # Debug logging for first chunk
        debug_logged = False
        
        while current_batch_size >= 1:
            try:
                # If we've reduced batch size, we need to split the chunk further
                if current_batch_size < original_frames.shape[0]:
                    # Process in sub-chunks of current_batch_size
                    sub_preds = []
                    for sub_start in range(0, original_frames.shape[0], current_batch_size):
                        sub_end = min(sub_start + current_batch_size, original_frames.shape[0])
                        sub_frames = original_frames[sub_start:sub_end]
                        sub_masks = original_masks[sub_start:sub_end]
                        
                        # Log debug info for first sub-chunk
                        if not debug_logged:
                            if use_roi:
                                logger.info(
                                    f"[ROI DEBUG] Input Shape: {sub_frames.shape}. " 
                                    f"ROI active, processing on device: {self.device}"
                                )
                            else:
                                logger.info(
                                    f"[ROI DEBUG] Input Shape: {sub_frames.shape}. " 
                                    f"Full-frame processing on device: {self.device}"
                                )
                            sys.stdout.flush()
                            debug_logged = True
                        
                        # Process sub-chunk using strategy
                        sub_pred = self.strategy.process_chunk(sub_frames, sub_masks, self.model_adapter)
                        sub_preds.append(sub_pred)
                        
                        # Clear cache after each sub-chunk
                        self.device_manager.empty_cache()
                        gc.collect()
                    
                    # Combine sub-chunks
                    return torch.cat(sub_preds, dim=0)
                else:
                    # Log debug info for whole chunk
                    if not debug_logged:
                        if use_roi:
                            logger.info(
                                f"[ROI DEBUG] Input Shape: {original_frames.shape}. " 
                                f"ROI active, processing on device: {self.device}"
                            )
                        else:
                            logger.info(
                                f"[ROI DEBUG] Input Shape: {original_frames.shape}. " 
                                f"Full-frame processing on device: {self.device}"
                            )
                        sys.stdout.flush()
                        debug_logged = True
                    
                    # Process whole chunk using strategy
                    return self.strategy.process_chunk(original_frames, original_masks, self.model_adapter)
                    
            except torch.OutOfMemoryError:
                # Clear cache and reduce batch size
                torch.cuda.empty_cache()
                gc.collect()
                
                new_batch_size = max(1, current_batch_size // 2)
                logger.warning(
                    f"OOM detected while processing chunk of size {current_batch_size}. " 
                    f"Retrying with batch size {new_batch_size}"
                )
                
                if new_batch_size == current_batch_size:
                    # Can't reduce batch size further - try downscaling before CPU fallback
                    if not self.downscaled and original_frames.shape[2] > self.target_height:
                        # Downscale frames and masks
                        logger.warning(
                            f"VRAM insufficient for {original_frames.shape[2]}x{original_frames.shape[3]}. " 
                            f"Auto-downscaling to {self.target_height}p to keep GPU acceleration."
                        )
                        downscaled_frames, downscaled_masks, scale_factor = self._downscale_frames(
                            original_frames, original_masks, self.target_height
                        )
                        # Update original frames and masks for retry
                        original_frames = downscaled_frames
                        original_masks = downscaled_masks
                        self.downscaled = True
                        self.scale_factor = scale_factor
                        # Reset batch size to initial (maybe we can increase batch size after downscaling)
                        current_batch_size = initial_batch_size
                        continue
                    
                    # If already downscaled or resolution already low, fallback to CPU
                    if not self.cpu_fallback_active:
                        self._enable_cpu_fallback()
                        # After moving to CPU, retry the same chunk
                        current_batch_size = initial_batch_size
                        continue
                    else:
                        # Already on CPU but still OOM? Should not happen, but raise
                        raise ProcessingError(
                            "CPU fallback active but still out of memory. " 
                            "This may indicate insufficient system RAM."
                        )
                
                current_batch_size = new_batch_size
                continue
        
        # If we exit loop, batch size < 1 (should not happen)
        raise ProcessingError(
            "Failed to process chunk even with batch size 1. " 
            "GPU VRAM insufficient for this resolution."
        )
    
    def _process_chunk_with_oom(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Process chunk using strategy (without OOM recovery).
        This is a simple wrapper that delegates to the strategy.
        """
        return self.strategy.process_chunk(frames, masks, self.model_adapter)
    
    def _process_single_frame(self, frame_path: Path, mask_path: Path, output_dir: Path) -> None:
        """
        Process a single frame with OOM recovery.
        
        Args:
            frame_path: Path to frame image
            mask_path: Path to mask image
            output_dir: Output directory
        """
        frame = cv2.imread(str(frame_path))
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if frame is None or mask is None:
            raise ProcessingError(f"Failed to load frame or mask: {frame_path}, {mask_path}")
        
        # Convert to tensors
        frame_t = torch.from_numpy(frame).permute(2, 0, 1).float() / 255.0
        mask_t = torch.from_numpy(mask).unsqueeze(0).float() / 255.0
        frame_t = frame_t.unsqueeze(0)  # Shape: [1, C, H, W]
        mask_t = mask_t.unsqueeze(0)    # Shape: [1, 1, H, W]
        
        frame_t = frame_t.to(self.device)
        mask_t = mask_t.to(self.device)
        
        # Process with OOM recovery
        current_batch_size = 1
        while current_batch_size >= 1:
            try:
                with torch.no_grad():
                    pred_t = self.model_adapter.process_chunk(frame_t, mask_t)
                break
            except torch.OutOfMemoryError:
                torch.cuda.empty_cache()
                gc.collect()
                new_batch_size = current_batch_size // 2
                logger.warning(f"OOM detected on single frame. Retrying with batch size {new_batch_size}")
                if new_batch_size == 0:
                    # Can't reduce batch size further - try downscaling before CPU fallback
                    if not self.downscaled and frame_t.shape[2] > self.target_height:
                        # Downscale single frame
                        logger.warning(
                            f"VRAM insufficient for {frame_t.shape[2]}x{frame_t.shape[3]}. "
                            f"Auto-downscaling to {self.target_height}p to keep GPU acceleration."
                        )
                        downscaled_frames, downscaled_masks, scale_factor = self._downscale_frames(
                            frame_t, mask_t, self.target_height
                        )
                        # Update tensors
                        frame_t = downscaled_frames
                        mask_t = downscaled_masks
                        self.downscaled = True
                        self.scale_factor = scale_factor
                        # Reset batch size and continue loop
                        current_batch_size = 1
                        continue
                    
                    # If already downscaled or resolution already low, fallback to CPU
                    if not self.cpu_fallback_active:
                        self._enable_cpu_fallback()
                        # After moving to CPU, retry the same frame
                        # Update tensors to CPU device
                        frame_t = frame_t.to(self.device)
                        mask_t = mask_t.to(self.device)
                        # Reset batch size and continue loop
                        current_batch_size = 1
                        continue
                    else:
                        # Already on CPU but still OOM? Should not happen, but raise
                        raise ProcessingError(
                            "CPU fallback active but still out of memory. "
                            "This may indicate insufficient system RAM."
                        )
                current_batch_size = new_batch_size
                # Note: batch size reduction doesn't make sense for single frame,
                # but we can try to downscale resolution (optional)
                # For now, just retry with cleared cache
                continue
        
        # Save processed frame
        pred = pred_t.squeeze(0).permute(1, 2, 0).cpu().numpy() * 255.0
        pred = pred.astype(np.uint8)
        output_path = output_dir / frame_path.name
        cv2.imwrite(str(output_path), pred)
        
        # Cleanup
        del frame, mask, frame_t, mask_t, pred_t, pred
        self.device_manager.empty_cache()
        gc.collect()
    
    def is_available(self) -> bool:
        """Check if subtitle remover is available (ProPainter + OCR)."""
        try:
            # Check OCR
            import paddleocr  # noqa: F401
            
            # Check ProPainter
            return self.propainter_loader.is_available()
            
        except ImportError:
            return False
