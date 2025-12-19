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
        
        # CPU fallback state
        self.cpu_fallback_active = False
        
        # Downscaling state
        self.downscaled = False
        self.target_height = 720  # target height for downscaling
        self.scale_factor = 1.0
        
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
        T, C, H, W = frames.shape
        if H <= target_height:
            # Already at or below target height
            return frames, masks, 1.0
        
        # Calculate new dimensions maintaining aspect ratio
        scale_factor = target_height / H
        new_h = target_height
        new_w = int(W * scale_factor)
        # Ensure dimensions are divisible by 8 for ProPainter
        new_h = ((new_h + 7) // 8) * 8
        new_w = ((new_w + 7) // 8) * 8
        
        logger.warning(
            f"VRAM insufficient for {H}x{W}. Auto-downscaling to {new_h}x{new_w} "
            f"(scale factor {scale_factor:.2f}) to keep GPU acceleration."
        )
        
        # Convert tensors to numpy for OpenCV resize
        frames_np = frames.permute(0, 2, 3, 1).cpu().numpy()  # (T, H, W, C)
        masks_np = masks.squeeze(1).cpu().numpy()  # (T, H, W)
        
        downscaled_frames = []
        downscaled_masks = []
        for i in range(T):
            frame = (frames_np[i] * 255).astype(np.uint8)
            mask = (masks_np[i] * 255).astype(np.uint8)
            
            frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            mask_resized = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            
            downscaled_frames.append(frame_resized)
            downscaled_masks.append(mask_resized)
        
        # Convert back to tensors
        downscaled_frames = np.stack(downscaled_frames)  # (T, new_h, new_w, C)
        downscaled_masks = np.stack(downscaled_masks)  # (T, new_h, new_w)
        
        frames_t = torch.from_numpy(downscaled_frames).permute(0, 3, 1, 2).float() / 255.0
        masks_t = torch.from_numpy(downscaled_masks).unsqueeze(1).float() / 255.0
        
        return frames_t.to(frames.device), masks_t.to(masks.device), scale_factor
    
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
            logger.info("Loading ProPainter model...")
            self.load_model()
            logger.info("ProPainter model loaded successfully")
            
            # Step 1: Generate masks (streaming)
            logger.info("Step 1/3: Generating masks...")
            temp_mask_dir = request.output_dir.parent / "tmp_masks_streaming"
            if temp_mask_dir.exists():
                shutil.rmtree(temp_mask_dir)
            
            logger.info(f"Generating masks for frames in {request.input_dir}")
            mask_dir = self.mask_service.generate_masks(
                input_dir=request.input_dir,
                output_dir=temp_mask_dir,
                batch_size=2  # Very small batch size for memory efficiency
            )
            logger.info(f"Masks generated successfully in {mask_dir}")
            
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
            
            # Estimate optimal chunk size for streaming
            # Use a sample frame to get dimensions
            sample_frame = cv2.imread(str(frame_paths[0]))
            if sample_frame is None:
                raise ProcessingError(f"Failed to load sample frame: {frame_paths[0]}")
            h, w = sample_frame.shape[:2]
            max_frames_per_chunk = self.device_manager.estimate_max_batch_size(
                frame_height=h,
                frame_width=w,
                model_memory_gb=2.0
            )
            # Limit chunk size for streaming (max 5 frames)
            max_frames_per_chunk = min(max_frames_per_chunk, 5)
            logger.info(f"Streaming chunk size: {max_frames_per_chunk} frames")
            
            total_frames = len(frame_paths)
            processed_count = 0
            chunk_start = 0
            
            # Calculate total chunks for logging
            total_chunks = (total_frames + max_frames_per_chunk - 1) // max_frames_per_chunk
            current_chunk = 0
            
            # Heartbeat logging
            heartbeat_interval = 30.0  # seconds
            last_heartbeat_time = time.time()
            last_logged_percentage = 0
            
            while chunk_start < total_frames:
                chunk_end = min(chunk_start + max_frames_per_chunk, total_frames)
                chunk_frame_paths = frame_paths[chunk_start:chunk_end]
                chunk_mask_paths = mask_paths[chunk_start:chunk_end]
                
                # Log chunk start BEFORE heavy processing (critical for observability)
                current_chunk += 1
                logger.info(
                    f"Processing chunk {current_chunk}/{total_chunks} "
                    f"(Frames {chunk_start}-{chunk_end-1})..."
                )
                
                # Load chunk frames and masks
                frames_list = []
                masks_list = []
                for frame_path, mask_path in zip(chunk_frame_paths, chunk_mask_paths):
                    frame = cv2.imread(str(frame_path))
                    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
                    if frame is None or mask is None:
                        logger.warning(f"Failed to load frame or mask: {frame_path}, {mask_path}")
                        # Use zero frame/mask as placeholder
                        frame = np.zeros((h, w, 3), dtype=np.uint8)
                        mask = np.zeros((h, w), dtype=np.uint8)
                    frames_list.append(frame)
                    masks_list.append(mask)
                
                # Convert to tensors - shape (T, C, H, W) and (T, 1, H, W)
                frames_t = torch.stack([
                    torch.from_numpy(f).permute(2, 0, 1).float() / 255.0
                    for f in frames_list
                ])  # (T, C, H, W)
                masks_t = torch.stack([
                    torch.from_numpy(m).unsqueeze(0).float() / 255.0
                    for m in masks_list
                ])  # (T, 1, H, W)
                
                # Process chunk with OOM recovery
                try:
                    pred_t = self._process_chunk_with_oom_recovery(frames_t, masks_t, max_frames_per_chunk)
                except Exception as e:
                    logger.error(f"Failed to process chunk {chunk_start}-{chunk_end}: {e}")
                    # Fallback to processing frames one by one
                    for idx, (frame_path, mask_path) in enumerate(zip(chunk_frame_paths, chunk_mask_paths)):
                        try:
                            self._process_single_frame(frame_path, mask_path, request.output_dir)
                            processed_count += 1
                        except Exception as single_error:
                            logger.error(f"Failed to process single frame {frame_path}: {single_error}")
                    chunk_start = chunk_end
                    continue
                
                # Save processed frames
                pred_frames = pred_t.permute(0, 2, 3, 1).cpu().numpy() * 255.0
                pred_frames = pred_frames.astype(np.uint8)
                chunk_size = len(chunk_frame_paths)
                for idx, frame_path in enumerate(chunk_frame_paths):
                    output_path = request.output_dir / frame_path.name
                    cv2.imwrite(str(output_path), pred_frames[idx])
                    processed_count += 1
                
                # Heartbeat logging (every 30 seconds or 10% progress)
                current_time = time.time()
                current_percentage = int((processed_count / total_frames) * 100)
                if (current_time - last_heartbeat_time >= heartbeat_interval) or (current_percentage >= last_logged_percentage + 10):
                    elapsed = current_time - start_time
                    fps = processed_count / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Processed {processed_count}/{total_frames} frames ({current_percentage}%) - "
                        f"Speed: {fps:.1f} fps - Device: {self.device}"
                    )
                    last_heartbeat_time = current_time
                    last_logged_percentage = current_percentage
                
                # Aggressive memory cleanup
                del frames_list, masks_list, frames_t, masks_t, pred_t, pred_frames
                self.device_manager.empty_cache()
                gc.collect()
                time.sleep(0.05)
                
                chunk_start = chunk_end
            
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
                        
                        # Process sub-chunk
                        sub_pred = self.model_adapter.process_chunk(sub_frames, sub_masks)
                        sub_preds.append(sub_pred)
                        
                        # Clear cache after each sub-chunk
                        self.device_manager.empty_cache()
                        gc.collect()
                    
                    # Combine sub-chunks
                    return torch.cat(sub_preds, dim=0)
                else:
                    # Process whole chunk
                    return self.model_adapter.process_chunk(original_frames, original_masks)
                    
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
