"""
SAM 2 wrapper for image segmentation.
Converts bounding boxes to precise pixel masks.
"""

import os
import torch
import numpy as np
from typing import List, Tuple
from src.shared.logging import get_logger

logger = get_logger(__name__)

class SAM2ImageWrapper:
    """Wrapper for SAM 2 image segmentation."""
    
    def __init__(self, checkpoint_path: str = None, model_cfg: str = "sam2_hiera_s.yaml"):
        """
        Initialize SAM 2 image wrapper.
        
        Args:
            checkpoint_path: Path to SAM 2 checkpoint. If None, uses default path.
            model_cfg: Model configuration file name.
        """
        self.checkpoint_path = checkpoint_path or "/opt/sam2_checkpoints/sam2_hiera_small.pt"
        self.model_cfg = model_cfg
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.predictor = None
        
    def _load_model(self):
        """Load SAM 2 model if not already loaded."""
        if self.predictor is None:
            logger.info(f"Loading SAM 2 model from {self.checkpoint_path}...")
            try:
                from sam2.build_sam import build_sam2
                self.predictor = build_sam2(self.model_cfg, self.checkpoint_path, device=self.device)
                logger.info("SAM 2 model loaded.")
            except ImportError as e:
                logger.error(f"Failed to import SAM 2: {e}")
                raise ImportError("SAM 2 is not installed. Please install it from https://github.com/facebookresearch/sam2")
            except Exception as e:
                logger.error(f"Failed to load SAM 2 model: {e}")
                raise RuntimeError(f"Failed to load SAM 2 model: {e}")
    
    def _unload_model(self):
        """Unload SAM 2 model to free memory."""
        if self.predictor is not None:
            del self.predictor
            self.predictor = None
            torch.cuda.empty_cache()
            logger.info("SAM 2 model unloaded to free VRAM.")
    
    def get_mask(self, image: np.ndarray, bboxes: List[List[float]]) -> np.ndarray:
        """
        Generate precise mask from bounding boxes using SAM 2.
        
        Args:
            image: Input image as numpy array (H, W, 3) in BGR format.
            bboxes: List of bounding boxes [[x1, y1, x2, y2], ...] in pixel coordinates.
            
        Returns:
            Binary mask as numpy array (H, W) with values 0 (background) or 255 (text).
        """
        if not bboxes:
            # No text detected, return empty mask
            h, w = image.shape[:2]
            return np.zeros((h, w), dtype=np.uint8)
        
        self._load_model()
        
        try:
            # Convert BGR to RGB for SAM 2
            image_rgb = image[:, :, ::-1].copy()
            
            # Prepare prompts for SAM 2
            # SAM 2 expects boxes in format [N, 4] where each box is [x1, y1, x2, y2]
            boxes_tensor = torch.tensor(bboxes, device=self.device, dtype=torch.float32)
            
            # Run SAM 2 inference
            with torch.no_grad():
                # Set image
                self.predictor.set_image(image_rgb)
                
                # Predict masks for all boxes
                masks, scores, _ = self.predictor.predict(
                    point_coords=None,
                    point_labels=None,
                    box=boxes_tensor,
                    multimask_output=False  # Single mask per box
                )
            
            # Combine all masks into a single mask
            # masks shape: (N, 1, H, W) where N is number of boxes
            combined_mask = torch.any(masks.squeeze(1) > 0, dim=0)
            
            # Convert to numpy and scale to 0-255
            mask_np = combined_mask.cpu().numpy().astype(np.uint8) * 255
            
            # Clear image from predictor to free memory
            self.predictor.reset_image()
            
            return mask_np
            
        except Exception as e:
            logger.error(f"SAM 2 mask generation failed: {e}")
            # Fallback: create mask from bounding boxes directly
            return self._create_fallback_mask(image, bboxes)
        finally:
            self._unload_model()
    
    def _create_fallback_mask(self, image: np.ndarray, bboxes: List[List[float]]) -> np.ndarray:
        """
        Fallback method: create mask directly from bounding boxes.
        Used when SAM 2 fails.
        """
        import cv2
        
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        for bbox in bboxes:
            x1, y1, x2, y2 = map(int, bbox)
            # Draw filled rectangle
            cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
        
        logger.warning("Using fallback mask generation (bounding boxes only)")
        return mask
    
    def process_image(self, image_path: str, bboxes: List[List[float]]) -> np.ndarray:
        """
        Convenience method: load image and generate mask.
        
        Args:
            image_path: Path to image file.
            bboxes: List of bounding boxes [[x1, y1, x2, y2], ...].
            
        Returns:
            Binary mask as numpy array.
        """
        import cv2
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Failed to load image: {image_path}")
        
        return self.get_mask(image, bboxes)
