"""
Tensor operations for image processing.
Includes resizing, scaling, and tensor conversions.
"""

import cv2
import numpy as np
import torch
import logging

logger = logging.getLogger(__name__)


def downscale_batch(frames: torch.Tensor, masks: torch.Tensor, target_height: int) -> tuple[torch.Tensor, torch.Tensor, float]:
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


def upscale_batch(frames: torch.Tensor, target_height: int, target_width: int) -> torch.Tensor:
    """
    Upscale frames to target dimensions.
    
    Args:
        frames: Frames tensor of shape (T, C, H, W)
        target_height: Target height in pixels
        target_width: Target width in pixels
        
    Returns:
        Upscaled frames tensor of shape (T, C, target_height, target_width)
    """
    T, C, H, W = frames.shape
    if H == target_height and W == target_width:
        return frames
    
    # Convert to numpy for OpenCV resize
    frames_np = frames.permute(0, 2, 3, 1).cpu().numpy()  # (T, H, W, C)
    
    upscaled_frames = []
    for i in range(T):
        frame = (frames_np[i] * 255).astype(np.uint8)
        frame_resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
        upscaled_frames.append(frame_resized)
    
    # Convert back to tensor
    upscaled_frames = np.stack(upscaled_frames)  # (T, target_height, target_width, C)
    upscaled_t = torch.from_numpy(upscaled_frames).permute(0, 3, 1, 2).float() / 255.0
    upscaled_t = upscaled_t.to(frames.device)
    
    return upscaled_t


def resize_batch_numpy(frames: list[np.ndarray], masks: list[np.ndarray], 
                       target_height: int, target_width: int) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Resize batch of numpy arrays to target dimensions.
    
    Args:
        frames: List of frame arrays (H, W, 3)
        masks: List of mask arrays (H, W)
        target_height: Target height
        target_width: Target width
        
    Returns:
        Tuple of (resized_frames, resized_masks)
    """
    resized_frames = []
    resized_masks = []
    
    for frame, mask in zip(frames, masks):
        frame_resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
        mask_resized = cv2.resize(mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST)
        resized_frames.append(frame_resized)
        resized_masks.append(mask_resized)
    
    return resized_frames, resized_masks


def tensor_to_numpy(frames: torch.Tensor, masks: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    """
    Convert frames and masks tensors to numpy arrays.
    
    Args:
        frames: Frames tensor of shape (T, C, H, W)
        masks: Masks tensor of shape (T, 1, H, W)
        
    Returns:
        Tuple of (frames_np, masks_np) where frames_np is (T, H, W, C) and masks_np is (T, H, W)
    """
    frames_np = frames.permute(0, 2, 3, 1).cpu().numpy()  # (T, H, W, C)
    masks_np = masks.squeeze(1).cpu().numpy()  # (T, H, W)
    return frames_np, masks_np


def numpy_to_tensor(frames_np: np.ndarray, masks_np: np.ndarray, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Convert numpy arrays to tensors.
    
    Args:
        frames_np: Frames array of shape (T, H, W, C)
        masks_np: Masks array of shape (T, H, W)
        device: Target device
        
    Returns:
        Tuple of (frames_tensor, masks_tensor)
    """
    frames_t = torch.from_numpy(frames_np).permute(0, 3, 1, 2).float() / 255.0
    masks_t = torch.from_numpy(masks_np).unsqueeze(1).float() / 255.0
    return frames_t.to(device), masks_t.to(device)


def maybe_downscale_numpy(frames: list[np.ndarray], masks: list[np.ndarray], 
                          target_height: int, auto_downscale: bool, 
                          use_roi_optimization: bool) -> tuple[list[np.ndarray], list[np.ndarray], float]:
    """
    Proactively downscale frames and masks if auto_downscale is enabled and height exceeds target.
    
    Args:
        frames: List of frame arrays (H, W, 3)
        masks: List of mask arrays (H, W)
        target_height: Target height for downscaling
        auto_downscale: Whether auto-downscaling is enabled
        use_roi_optimization: Whether ROI optimization is enabled
        
    Returns:
        Tuple of (downscaled_frames, downscaled_masks, scale_factor)
    """
    if not auto_downscale or len(frames) == 0:
        return frames, masks, 1.0
    
    h, w = frames[0].shape[:2]
    if h <= target_height:
        return frames, masks, 1.0
    
    # If ROI optimization is enabled, we'll process only the bottom region at full resolution
    # Skip downscaling to preserve quality
    if use_roi_optimization:
        logger.info(
            f"High resolution detected ({h}x{w}). "
            f"ROI optimization active, using dynamic cropping to preserve quality."
        )
        return frames, masks, 1.0
    
    # Calculate new dimensions maintaining aspect ratio
    scale_factor = target_height / h
    new_h = target_height
    new_w = int(w * scale_factor)
    # Ensure dimensions are divisible by 8 for ProPainter
    new_h = ((new_h + 7) // 8) * 8
    new_w = ((new_w + 7) // 8) * 8
    
    logger.warning(
        f"High resolution detected ({h}x{w}). "
        f"Auto-downscaling to {new_h}x{new_w} (scale factor {scale_factor:.2f}) for stability."
    )
    
    downscaled_frames = []
    downscaled_masks = []
    for frame, mask in zip(frames, masks):
        frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        mask_resized = cv2.resize(mask, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        downscaled_frames.append(frame_resized)
        downscaled_masks.append(mask_resized)
    
    return downscaled_frames, downscaled_masks, scale_factor
