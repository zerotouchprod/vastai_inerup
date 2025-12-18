"""
ProPainter model adapter for handling different API versions.
"""

import inspect
import logging
from typing import Callable, Optional
import torch
import torch.nn as nn

from src.core.exceptions import ModelLoadingError

logger = logging.getLogger(__name__)


class ProPainterModelAdapter:
    """Adapter for ProPainter model to handle different API versions."""
    
    def __init__(self, model: nn.Module, device: torch.device):
        """
        Initialize ProPainter model adapter.
        
        Args:
            model: ProPainter model
            device: Torch device
        """
        self.model = model
        self.device = device
        self.forward_method = self._inspect_model_signature(model)
        self.autocast_enabled = device.type == 'cuda'
        
        logger.info(f"ProPainter adapter initialized (device: {device}, autocast: {self.autocast_enabled})")
    
    def _inspect_model_signature(self, model: nn.Module) -> Callable:
        """
        Inspect model forward signature and return adapted method.
        
        Args:
            model: ProPainter model
            
        Returns:
            Adapted forward method
            
        Raises:
            ModelLoadingError: If model signature cannot be determined
        """
        try:
            sig = inspect.signature(model.forward)
            params = list(sig.parameters.keys())
            logger.info(f"Model forward signature: {sig}")
            logger.info(f"Parameters: {params}")
            logger.info(f"Number of parameters: {len(params)}")
            
            # Create adapted method based on signature
            if len(params) == 2:
                # Old API: forward(frames, masks)
                def forward_adapter(frames, masks):
                    return self.model(frames, masks)
                    
            elif len(params) == 3:
                # Intermediate API: forward(frames, masks_in, masks_updated)
                def forward_adapter(frames, masks):
                    return self.model(frames, masks, masks)
                    
            elif len(params) == 4:
                # New API: forward(frames, masks_in, masks_updated, num_local_frames)
                def forward_adapter(frames, masks):
                    return self.model(frames, masks, masks, 10)
                    
            elif len(params) == 5:
                # API: forward(frames, masks_in, masks_updated, num_local_frames, device)
                def forward_adapter(frames, masks):
                    return self.model(frames, masks, masks, 10, self.device)
                    
            elif len(params) == 7:
                # Latest API: forward(masked_frames, completed_flows, masks_in, masks_updated, num_local_frames, interpolation, t_dilation)
                def forward_adapter(frames, masks):
                    b, t, c, h, w = frames.shape
                    completed_flows = torch.zeros((b, t - 1, 2, h, w), device=frames.device)
                    return self.model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)
                    
            else:
                raise ValueError(f"Unsupported number of parameters: {len(params)}")
            
            logger.info(f"Using adapted forward method for {len(params)}-parameter API")
            return forward_adapter
            
        except Exception as sig_error:
            logger.warning(f"Could not inspect signature: {sig_error}. Using fallback adapter...")
            return self._create_fallback_adapter()
    
    def _create_fallback_adapter(self) -> Callable:
        """Create fallback adapter that tries different API versions."""
        
        def fallback_adapter(frames, masks):
            # Try different API versions in order of likelihood
            
            # Version 1: API with 7 arguments (latest)
            try:
                b, t, c, h, w = frames.shape
                completed_flows = torch.zeros((b, t - 1, 2, h, w), device=frames.device)
                return self.model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)
            except (TypeError, AttributeError) as e1:
                logger.debug(f"API 7-args failed: {e1}")
                
                # Version 2: API with 5 arguments
                try:
                    return self.model(frames, masks, masks, 10, self.device)
                except TypeError as e2:
                    logger.debug(f"API 5-args failed: {e2}")
                    
                    # Version 3: API with 4 arguments
                    try:
                        return self.model(frames, masks, masks, 10)
                    except TypeError as e3:
                        logger.debug(f"API 4-args failed: {e3}")
                        
                        # Version 4: API with 3 arguments
                        try:
                            return self.model(frames, masks, masks)
                        except TypeError as e4:
                            logger.debug(f"API 3-args failed: {e4}")
                            
                            # Version 5: Old API with 2 arguments
                            try:
                                return self.model(frames, masks)
                            except TypeError as e5:
                                logger.error(f"All API attempts failed: {e5}")
                                raise ModelLoadingError(f"Could not find compatible ProPainter API. Error: {e5}")
        
        logger.info("Using fallback adapter (tries multiple API versions)")
        return fallback_adapter
    
    def predict(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Run prediction with the adapted model.
        
        Args:
            frames: Input frames tensor of shape (1, T, C, H, W)
            masks: Input masks tensor of shape (1, T, 1, H, W)
            
        Returns:
            Predicted frames tensor of shape (T, C, H, W)
        """
        # Ensure masks are binary
        masks = (masks > 0.5).float()
        
        # Create masked input
        masked_input = frames * (1 - masks)
        
        # Apply padding if needed (multiple of 8)
        b, t, c, h, w = masked_input.shape
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8
        
        if pad_h > 0 or pad_w > 0:
            import torch.nn.functional as F
            masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
            masks = F.pad(masks, (0, pad_w, 0, pad_h))
        
        # Run inference
        with torch.no_grad():
            if self.autocast_enabled:
                from torch.cuda.amp import autocast
                with autocast():
                    pred_frames = self.forward_method(masked_input, masks)
            else:
                pred_frames = self.forward_method(masked_input, masks)
        
        # Remove padding
        pred_frames = pred_frames[0, :, :, :h, :w]
        
        return pred_frames
    
    def process_chunk(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Process a chunk of frames.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        # Add batch dimension
        frames_batch = frames.unsqueeze(0).to(self.device)
        masks_batch = masks.unsqueeze(0).to(self.device)
        
        # Run prediction
        return self.predict(frames_batch, masks_batch)
