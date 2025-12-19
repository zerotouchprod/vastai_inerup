"""
Strict Dynamic Tiling Strategy for subtitle removal.
Enforces bounding box crop as the ONLY strategy to prevent OOM.
"""

import torch
import numpy as np
import logging
from typing import Optional, Tuple

from src.infrastructure.image_processing import geometry
from src.infrastructure.image_processing import tensor_ops

logger = logging.getLogger(__name__)


class DynamicTilingStrategy:
    """
    "The Surgeon" strategy: precise bounding box crop only.
    Takes full frame + model adapter, returns processed frame.
    """
    
    def __init__(self, config):
        """
        Initialize strict dynamic tiling strategy.
        
        Args:
            config: Configuration object with PADDING_PX, MAX_CROP_AREA_RATIO, etc.
        """
        self.padding_px = config.PADDING_PX
        self.max_crop_area_ratio = config.MAX_CROP_AREA_RATIO
        self.target_height = config.MAX_HEIGHT
    
    def process_chunk(self, frames: torch.Tensor, masks: torch.Tensor, 
                      model_adapter) -> torch.Tensor:
        """
        Process chunk of frames using strict dynamic tiling strategy.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        T, C, H, W = frames.shape
        
        # If no masks, return original frames
        if masks.sum().item() < 10.0:
            logger.debug("No subtitles detected in chunk, returning original frames")
            return frames
        
        # Calculate bounding box from UNION mask (max over time dimension)
        # This ensures we catch "jumping" text across frames
        y1, y2, x1, x2 = geometry.calculate_bounding_box(masks, self.padding_px)
        
        # Check if no masks found
        if y1 == y2 or x1 == x2:
            return frames
        
        # Calculate crop dimensions
        crop_h = y2 - y1
        crop_w = x2 - x1
        crop_area = crop_h * crop_w
        total_area = H * W
        
        # Safety check: if crop is too large, downscale only the crop
        max_safe_pixels = self.max_crop_area_ratio * total_area
        
        logger.info(
            f"Surgeon Mode: Processing crop {crop_w}x{crop_h} at Y={y1}:{y2}, X={x1}:{x2}. "
            f"Memory load: {'Low' if crop_area <= max_safe_pixels else 'High (downscaling crop)'}"
        )
        
        if crop_area > max_safe_pixels:
            # Crop is too large, downscale only the crop
            return self._process_downscaled_crop(frames, masks, y1, y2, x1, x2, model_adapter)
        else:
            # Process crop at native resolution
            return self._process_crop(frames, masks, y1, y2, x1, x2, model_adapter)
    
    def _process_crop(self, frames: torch.Tensor, masks: torch.Tensor,
                      y1: int, y2: int, x1: int, x2: int,
                      model_adapter) -> torch.Tensor:
        """
        Process crop at native resolution.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            y1, y2, x1, x2: Crop coordinates
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor with inpainted crop region
        """
        T, C, H, W = frames.shape
        
        # Crop frames and masks
        crop_frames = frames[:, :, y1:y2, x1:x2]
        crop_masks = masks[:, :, y1:y2, x1:x2]
        
        # Process crop
        processed_crop = model_adapter.process_chunk(crop_frames, crop_masks)
        
        # Ensure same dtype and device as original frames
        if processed_crop.dtype != frames.dtype:
            processed_crop = processed_crop.to(frames.dtype)
        if processed_crop.device != frames.device:
            processed_crop = processed_crop.to(frames.device)
        
        # Stitch back into full frames
        processed_frames = frames.clone()
        processed_frames[:, :, y1:y2, x1:x2] = processed_crop
        
        return processed_frames
    
    def _process_downscaled_crop(self, frames: torch.Tensor, masks: torch.Tensor,
                                 y1: int, y2: int, x1: int, x2: int,
                                 model_adapter) -> torch.Tensor:
        """
        Process a large crop by downscaling it to safe size, inpainting, then upscaling back.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            y1, y2, x1, x2: Crop coordinates
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor with inpainted crop region
        """
        T, C, H, W = frames.shape
        crop_h = y2 - y1
        crop_w = x2 - x1
        
        # Calculate safe limit
        total_area = H * W
        max_safe_pixels = self.max_crop_area_ratio * total_area
        current_area = crop_h * crop_w
        
        # Calculate scale factor to fit within safe limit
        scale = geometry.calculate_safe_scale(current_area, max_safe_pixels)
        
        # Calculate new dimensions (divisible by 8)
        new_h = int(crop_h * scale)
        new_w = int(crop_w * scale)
        new_h = geometry.align_to_grid(new_h, 8)
        new_w = geometry.align_to_grid(new_w, 8)
        
        logger.warning(
            f"Crop too large ({current_area} px). Downscaling crop by factor {scale:.2f} "
            f"to {new_h}x{new_w} to force removal."
        )
        
        # Extract crop
        crop_frames = frames[:, :, y1:y2, x1:x2]
        crop_masks = masks[:, :, y1:y2, x1:x2]
        
        # Downscale crop
        downscaled_frames, downscaled_masks, _ = tensor_ops.downscale_batch(
            crop_frames, crop_masks, new_h
        )
        
        # Process downscaled crop
        processed_downscaled = model_adapter.process_chunk(downscaled_frames, downscaled_masks)
        
        # Upscale back to original crop dimensions
        upscaled_crop = tensor_ops.upscale_batch(processed_downscaled, crop_h, crop_w)
        
        # Stitch back into full frames
        processed_frames = frames.clone()
        processed_frames[:, :, y1:y2, x1:x2] = upscaled_crop
        
        return processed_frames
