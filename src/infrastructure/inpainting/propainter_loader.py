"""
ProPainter model loader with safe imports and path management.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Tuple

import torch

from src.core.exceptions import ModelLoadingError

logger = logging.getLogger(__name__)


class ProPainterLoader:
    """Loader for ProPainter model with safe import handling."""
    
    def __init__(self, propainter_root: Optional[Path] = None):
        """
        Initialize ProPainter loader.
        
        Args:
            propainter_root: Path to ProPainter root directory
        """
        self.propainter_root = propainter_root or Path(os.getenv("PROPAINTER_ROOT", "/opt/ProPainter"))
        self._model = None
        self._weights_loaded = False
        
    def add_to_sys_path(self) -> None:
        """Add ProPainter root to sys.path if not already present."""
        if str(self.propainter_root) not in sys.path:
            sys.path.append(str(self.propainter_root))
            logger.debug(f"Added {self.propainter_root} to sys.path")
    
    def check_weights_exist(self) -> bool:
        """Check if ProPainter weights exist."""
        weights_path = self.propainter_root / "weights/ProPainter.pth"
        exists = weights_path.exists()
        
        if not exists:
            logger.warning(f"ProPainter weights not found: {weights_path}")
        
        return exists
    
    def get_weights_path(self) -> Path:
        """Get path to ProPainter weights."""
        weights_path = self.propainter_root / "weights/ProPainter.pth"
        if not weights_path.exists():
            raise ModelLoadingError(f"ProPainter weights not found: {weights_path}")
        return weights_path
    
    def import_propainter_modules(self) -> Tuple:
        """
        Import ProPainter modules safely.
        
        Returns:
            Tuple of (InpaintGenerator, read_frame_from_videos) modules
            
        Raises:
            ModelLoadingError: If modules cannot be imported
        """
        self.add_to_sys_path()
        
        try:
            from model.propainter import InpaintGenerator
            from inference_propainter import read_frame_from_videos
            
            logger.info("Successfully imported ProPainter modules")
            return InpaintGenerator, read_frame_from_videos
            
        except ImportError as e:
            raise ModelLoadingError(f"Failed to import ProPainter modules: {e}")
    
    def load_model(self, device: torch.device) -> torch.nn.Module:
        """
        Load ProPainter model on specified device.
        
        Args:
            device: Torch device to load model on
            
        Returns:
            Loaded ProPainter model
            
        Raises:
            ModelLoadingError: If model cannot be loaded
        """
        if self._model is not None:
            return self._model
        
        try:
            # Import modules
            InpaintGenerator, _ = self.import_propainter_modules()
            
            # Get weights path
            weights_path = self.get_weights_path()
            
            logger.info(f"Loading ProPainter model from {weights_path}")
            
            # Create model on CPU first
            logger.info("Creating ProPainter model on CPU...")
            model = InpaintGenerator(model_path=str(weights_path))
            
            # Move to device if available
            if device.type == 'cuda':
                try:
                    logger.info("Moving model to CUDA device...")
                    model = model.to(device)
                    
                    # Verify model is on GPU
                    model_device = next(model.parameters()).device
                    if model_device.type == 'cuda':
                        # Clear CUDA cache
                        torch.cuda.empty_cache()
                        
                        # Monitor memory
                        allocated = torch.cuda.memory_allocated() / 1024 ** 3
                        reserved = torch.cuda.memory_reserved() / 1024 ** 3
                        logger.info(f"GPU memory after loading: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved")
                    else:
                        logger.warning(f"Model loaded on {model_device}, expected cuda")
                        
                except Exception as e:
                    logger.error(f"Failed to move model to CUDA: {e}. Keeping on CPU.")
                    device = torch.device("cpu")
            else:
                logger.info("Model loaded on CPU")
            
            model.eval()
            self._model = model
            self._weights_loaded = True
            
            # Log model device
            model_device = next(model.parameters()).device
            logger.info(f"ProPainter model loaded on device: {model_device}")
            
            return model
            
        except Exception as e:
            raise ModelLoadingError(f"Failed to load ProPainter model: {e}")
    
    def is_available(self) -> bool:
        """Check if ProPainter is available (modules and weights)."""
        try:
            # Check weights
            if not self.check_weights_exist():
                return False
            
            # Try to import modules
            self.import_propainter_modules()
            return True
            
        except Exception as e:
            logger.debug(f"ProPainter not available: {e}")
            return False
