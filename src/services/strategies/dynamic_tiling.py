"""
Dynamic tiling strategy for subtitle removal.
Encapsulates the logic of crop-based processing with fallbacks.
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
    Strategy for dynamic mask-guided tiling.
    Takes full frame + model adapter, returns processed frame.
    """
    
    def __init__(self, config):
        """
        Initialize dynamic tiling strategy.
        
        Args:
            config: Configuration object with PADDING_PX, MAX_CROP_AREA_RATIO, etc.
        """
        self.padding_px = config.PADDING_PX
        self.max_crop_area_ratio = config.MAX_CROP_AREA_RATIO
        self.target_height = config.MAX_HEIGHT
        self.use_roi_optimization = config.USE_ROI_OPTIMIZATION
        self.roi_zone_height_ratio = config.ROI_ZONE_HEIGHT_RATIO
    
    def process_chunk(self, frames: torch.Tensor, masks: torch.Tensor, 
                      model_adapter) -> torch.Tensor:
        """
        Process chunk of frames using dynamic tiling strategy.
        
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
        
        # Determine processing strategy
        if self.use_roi_optimization and H > self.target_height:
            # Use ROI-based processing for high resolution
            return self._process_roi_chunk(frames, masks, model_adapter)
        else:
            # Use dynamic crop processing
            return self._process_dynamic_crop(frames, masks, model_adapter)
    
    def _process_dynamic_crop(self, frames: torch.Tensor, masks: torch.Tensor, 
                              model_adapter) -> torch.Tensor:
        """
        Process frames using dynamic mask-guided tiling.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        T, C, H, W = frames.shape
        
        # Calculate bounding box
        y1, y2, x1, x2 = geometry.calculate_bounding_box(masks, self.padding_px)
        
        # Check if no masks found
        if y1 == y2 or x1 == x2:
            return frames
        
        # Check safety (don't OOM on full screen text)
        crop_area = (y2 - y1) * (x2 - x1)
        total_area = H * W
        max_safe_pixels = self.max_crop_area_ratio * total_area
        
        if crop_area > max_safe_pixels:
            logger.warning(
                f"Crop area {crop_area} exceeds safe limit {max_safe_pixels:.0f} "
                f"({self.max_crop_area_ratio*100:.0f}% of frame). Falling back to downscaled crop processing."
            )
            return self._process_downscaled_crop(frames, masks, y1, y2, x1, x2, model_adapter)
        
        # Log the crop region
        logger.info(
            f"Dynamic Crop: Processing area Y={y1}:{y2}, X={x1}:{x2} "
            f"(Size: {(y2-y1)}x{(x2-x1)})."
        )
        
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
    
    def _process_roi_chunk(self, frames: torch.Tensor, masks: torch.Tensor,
                           model_adapter) -> torch.Tensor:
        """
        Process the best ROI zone (top, middle, bottom) based on mask distribution.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor of shape (T, C, H, W) with inpainted ROI.
        """
        T, C, H, W = frames.shape
        
        # Calculate ROI zone height
        roi_height = geometry.calculate_roi_zone_height(H, self.roi_zone_height_ratio)
        
        # Select best zone
        zone_type, y_start, roi_height = geometry.select_best_roi_zone(masks, roi_height)
        
        if zone_type is None:
            # No subtitles or fallback
            if masks.sum().item() < 10.0:
                # No subtitles, return original frames
                logger.debug("No subtitles detected, returning original frames")
                return frames
            else:
                # Fallback to split-frame processing
                return self._process_split_frame(frames, masks, model_adapter)
        
        # Handle split‑frame fallback
        if zone_type == 'split':
            logger.info("Dynamic Zone: Using split‑frame processing (masks span multiple zones)")
            return self._process_split_frame(frames, masks, model_adapter)
        
        logger.info(
            f"Dynamic Zone: Processing {zone_type} ROI {W}x{roi_height} (Start Y: {y_start})"
        )
        
        # Crop ROI
        frames_roi = frames[:, :, y_start:y_start+roi_height, :]  # (T, C, roi_height, W)
        masks_roi = masks[:, :, y_start:y_start+roi_height, :]    # (T, 1, roi_height, W)
        
        # Process ROI
        processed_roi = model_adapter.process_chunk(frames_roi, masks_roi)
        
        # Ensure same dtype and device as original frames
        if processed_roi.dtype != frames.dtype:
            processed_roi = processed_roi.to(frames.dtype)
        if processed_roi.device != frames.device:
            processed_roi = processed_roi.to(frames.device)
        
        # Stitch back into full frames
        processed_frames = frames.clone()
        processed_frames[:, :, y_start:y_start+roi_height, :] = processed_roi
        
        return processed_frames
    
    def _process_split_frame(self, frames: torch.Tensor, masks: torch.Tensor,
                             model_adapter) -> torch.Tensor:
        """
        Process full frame by splitting into top and bottom halves at native resolution.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        T, C, H, W = frames.shape
        logger.info(
            f"High‑Res Fallback: Processing frame in 2 splits (Top/Bottom) to maintain {H}p quality."
        )
        
        # Determine split height (60% of frame, aligned to 8)
        split_h = (int(H * 0.6) // 8) * 8
        if split_h == 0:
            split_h = 8
        
        # Top split: 0 to split_h
        frames_top = frames[:, :, :split_h, :]
        masks_top = masks[:, :, :split_h, :]
        
        # Bottom split: H - split_h to H
        start_bottom = H - split_h
        frames_bot = frames[:, :, start_bottom:, :]
        masks_bot = masks[:, :, start_bottom:, :]
        
        # Process splits sequentially (only if they contain masks)
        processed_frames = frames.clone()
        
        if masks_top.sum().item() > 10.0:
            logger.debug(f"Processing top split (height {split_h})")
            out_top = model_adapter.process_chunk(frames_top, masks_top)
            # Ensure dtype/device match
            if out_top.dtype != frames.dtype:
                out_top = out_top.to(frames.dtype)
            if out_top.device != frames.device:
                out_top = out_top.to(frames.device)
            processed_frames[:, :, :split_h, :] = out_top
        
        if masks_bot.sum().item() > 10.0:
            logger.debug(f"Processing bottom split (height {split_h})")
            out_bot = model_adapter.process_chunk(frames_bot, masks_bot)
            if out_bot.dtype != frames.dtype:
                out_bot = out_bot.to(frames.dtype)
            if out_bot.device != frames.device:
                out_bot = out_bot.to(frames.device)
            processed_frames[:, :, start_bottom:, :] = out_bot
        
        return processed_frames
    
    def _process_full_frame_downscaled(self, frames: torch.Tensor, masks: torch.Tensor,
                                       model_adapter) -> torch.Tensor:
        """
        Process full frames by downscaling to target height, then upscaling back.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            model_adapter: Model adapter for processing
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        T, C, H, W = frames.shape
        logger.warning(
            f"VRAM insufficient for split processing. Falling back to downscaled processing "
            f"({H}x{W} -> {self.target_height}p)."
        )
        
        # Downscale frames and masks
        downscaled_frames, downscaled_masks, scale_factor = tensor_ops.downscale_batch(
            frames, masks, self.target_height
        )
        
        # Process downscaled frames
        processed_downscaled = model_adapter.process_chunk(downscaled_frames, downscaled_masks)
        
        # Upscale back to original dimensions
        upscaled_frames = tensor_ops.upscale_batch(processed_downscaled, H, W)
        
        return upscaled_frames
