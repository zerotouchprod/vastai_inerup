"""
Device utilities for GPU/CPU selection and memory management.
"""

import os
import torch
import logging
from typing import Optional

from .exceptions import DeviceInitializationError

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages device selection and memory management."""
    
    def __init__(self, force_cpu: bool = False):
        """
        Initialize device manager.
        
        Args:
            force_cpu: Force CPU usage even if GPU is available
        """
        self.force_cpu = force_cpu
        self.device = self._init_device()
        
    def _init_device(self) -> torch.device:
        """Initialize device (CPU/CUDA) with safe fallback."""
        # Configure PyTorch environment variables for better memory management
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:128'
        os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
        
        if self.force_cpu:
            logger.info("CPU forced by configuration")
            return torch.device("cpu")
        
        cuda_available = False
        cuda_error = None
        
        try:
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_count = torch.cuda.device_count()
                if device_count > 0:
                    device_name = torch.cuda.get_device_name(0)
                    logger.info(f"CUDA GPU detected: {device_name}")
                    logger.info(f"CUDA version: {torch.version.cuda}")
                else:
                    cuda_available = False
                    logger.warning("CUDA available but no GPU devices found")
        except Exception as e:
            cuda_available = False
            cuda_error = str(e)
            logger.warning(f"CUDA check failed: {e}")
        
        # Select device with safe fallback
        if cuda_available:
            try:
                device = torch.device("cuda")
                # Test device with a simple operation
                test_tensor = torch.tensor([1.0]).cuda()
                del test_tensor
                torch.cuda.empty_cache()
                logger.info(f"Using CUDA device: {device}")
                logger.info(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
                return device
            except Exception as e:
                logger.error(f"CUDA device failed: {e}. Falling back to CPU.")
                return torch.device("cpu")
        else:
            if cuda_error:
                logger.warning(f"CUDA not available: {cuda_error}. Using CPU.")
            else:
                logger.info("Using CPU device")
            return torch.device("cpu")
    
    def get_device(self) -> torch.device:
        """Get the configured device."""
        return self.device
    
    def is_cuda_available(self) -> bool:
        """Check if CUDA is available and working."""
        return self.device.type == 'cuda'
    
    def get_memory_info(self) -> Optional[dict]:
        """Get memory information for the current device."""
        if self.device.type == 'cuda':
            try:
                allocated = torch.cuda.memory_allocated() / 1e9  # GB
                reserved = torch.cuda.memory_reserved() / 1e9  # GB
                total = torch.cuda.get_device_properties(0).total_memory / 1e9  # GB
                free = total - allocated
                
                return {
                    'total_gb': total,
                    'allocated_gb': allocated,
                    'reserved_gb': reserved,
                    'free_gb': free
                }
            except Exception as e:
                logger.warning(f"Failed to get GPU memory info: {e}")
                return None
        return None
    
    def empty_cache(self) -> None:
        """Empty CUDA cache if using GPU."""
        if self.device.type == 'cuda':
            torch.cuda.empty_cache()
            logger.debug("CUDA cache emptied")
    
    def estimate_max_batch_size(self, frame_height: int, frame_width: int, model_memory_gb: float = 2.0) -> int:
        """
        Estimate maximum batch size based on available memory.
        
        Args:
            frame_height: Frame height in pixels
            frame_width: Frame width in pixels
            model_memory_gb: Estimated model memory usage in GB
            
        Returns:
            Maximum number of frames to process at once
        """
        if self.device.type == 'cuda':
            try:
                memory_info = self.get_memory_info()
                if memory_info:
                    free_memory = memory_info['free_gb']
                    
                    # Empirical formula: each 720p frame requires ~0.1 GB memory
                    # Adjust based on actual frame size
                    base_frame_size = 1280 * 720  # 720p
                    actual_frame_size = frame_height * frame_width
                    scale_factor = actual_frame_size / base_frame_size
                    
                    # Safe coefficient: use only 50% of free memory for ProPainter (Transformer attention O(T^2))
                    safe_memory = free_memory * 0.5
                    available_for_frames = max(0, safe_memory - model_memory_gb)
                    
                    estimated_frames_per_gb = 10 / scale_factor  # Adjusted for frame size
                    max_frames_per_chunk = int(available_for_frames * estimated_frames_per_gb)
                    
                    # Limits: minimum 1, maximum 20 frames (more conservative)
                    max_frames_per_chunk = max(1, min(max_frames_per_chunk, 20))
                    
                    logger.info(f"Estimated max batch size: {max_frames_per_chunk} frames "
                               f"(free memory: {free_memory:.2f} GB)")
                    return max_frames_per_chunk
            except Exception as e:
                logger.warning(f"Could not determine GPU memory, using default: {e}")
        
        # Default values
        return 30 if self.device.type == 'cpu' else 15


# Global device manager instance
_device_manager: Optional[DeviceManager] = None


def get_device_manager(force_cpu: bool = False) -> DeviceManager:
    """Get or create device manager instance."""
    global _device_manager
    if _device_manager is None:
        _device_manager = DeviceManager(force_cpu=force_cpu)
    return _device_manager
