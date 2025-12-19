"""
Debug visualization utilities for masks and overlays.
"""

import cv2
import numpy as np
import torch
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class MaskVisualizer:
    """Visualizer for debug masks and overlays."""
    
    def __init__(self, output_dir: Path, enabled: bool = False):
        """
        Initialize mask visualizer.
        
        Args:
            output_dir: Base output directory for debug files
            enabled: Whether debug visualization is enabled
        """
        self.output_dir = output_dir
        self.enabled = enabled
        
        if self.enabled:
            self.debug_dir = output_dir / "masks_debug"
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Debug mask visualization enabled. Output directory: {self.debug_dir}")
    
    def save_debug_masks(self, frames: torch.Tensor, masks: torch.Tensor, batch_idx: int) -> None:
        """
        Save debug masks for visual inspection.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            batch_idx: Batch index for naming
        """
        if not self.enabled:
            return
        
        # Convert tensors to numpy
        frames_np = frames.permute(0, 2, 3, 1).cpu().numpy()  # (T, H, W, C)
        masks_np = masks.squeeze(1).cpu().numpy()  # (T, H, W)
        
        for i in range(frames.shape[0]):
            # Save mask
            mask = (masks_np[i] * 255).astype(np.uint8)
            mask_path = self.debug_dir / f"mask_batch{batch_idx:03d}_frame{i:03d}.png"
            cv2.imwrite(str(mask_path), mask)
            
            # Save frame with mask overlay for visualization
            frame = (frames_np[i] * 255).astype(np.uint8)
            overlay = frame.copy()
            # Create red overlay where mask is non-zero
            overlay[masks_np[i] > 0.5] = [0, 0, 255]  # BGR red
            overlay_path = self.debug_dir / f"overlay_batch{batch_idx:03d}_frame{i:03d}.png"
            cv2.imwrite(str(overlay_path), overlay)
        
        logger.debug(f"Saved debug masks to {self.debug_dir}")
    
    def save_single_mask(self, frame: np.ndarray, mask: np.ndarray, name: str) -> None:
        """
        Save single mask and overlay.
        
        Args:
            frame: Frame array (H, W, 3)
            mask: Mask array (H, W)
            name: Base name for output files
        """
        if not self.enabled:
            return
        
        # Save mask
        mask_path = self.debug_dir / f"{name}_mask.png"
        cv2.imwrite(str(mask_path), mask)
        
        # Save overlay
        overlay = frame.copy()
        overlay[mask > 127] = [0, 0, 255]  # BGR red
        overlay_path = self.debug_dir / f"{name}_overlay.png"
        cv2.imwrite(str(overlay_path), overlay)
    
    def save_bounding_box(self, frame: np.ndarray, y1: int, y2: int, x1: int, x2: int, name: str) -> None:
        """
        Save frame with bounding box visualization.
        
        Args:
            frame: Frame array (H, W, 3)
            y1, y2, x1, x2: Bounding box coordinates
            name: Base name for output file
        """
        if not self.enabled:
            return
        
        # Draw bounding box
        frame_with_box = frame.copy()
        cv2.rectangle(frame_with_box, (x1, y1), (x2, y2), (0, 255, 0), 2)
        
        box_path = self.debug_dir / f"{name}_bbox.png"
        cv2.imwrite(str(box_path), frame_with_box)
    
    @staticmethod
    def create_overlay(frame: np.ndarray, mask: np.ndarray, color: tuple = (0, 0, 255)) -> np.ndarray:
        """
        Create overlay of mask on frame.
        
        Args:
            frame: Frame array (H, W, 3)
            mask: Mask array (H, W)
            color: BGR color for overlay
            
        Returns:
            Overlay image
        """
        overlay = frame.copy()
        overlay[mask > 0] = color
        return overlay
    
    @staticmethod
    def blend_overlay(frame: np.ndarray, mask: np.ndarray, alpha: float = 0.5) -> np.ndarray:
        """
        Blend mask overlay with frame.
        
        Args:
            frame: Frame array (H, W, 3)
            mask: Mask array (H, W)
            alpha: Blend alpha (0-1)
            
        Returns:
            Blended image
        """
        overlay = np.zeros_like(frame)
        overlay[mask > 0] = [0, 0, 255]  # BGR red
        
        blended = cv2.addWeighted(frame, 1 - alpha, overlay, alpha, 0)
        return blended
