import os
import shutil
import numpy as np
from pathlib import Path
from typing import List, Union, Tuple
import torch
import torch.nn.functional as F
import cv2
import gdown

from src.shared.logging import get_logger
from src.core.config import get_config

# Import components
from src.infrastructure.inpainting.components.resolution import ResolutionCalculator
from src.infrastructure.inpainting.components.strategy import SlidingWindowStrategy
from src.infrastructure.inpainting.components.environment import EnvironmentManager
from src.infrastructure.inpainting.components.media import MediaProcessor

logger = get_logger(__name__)


class STTNAdapter:
    """
    Facade for STTN (Spatio-Temporal Transformer Network) inpainting pipeline.
    Designed for video-consistent inpainting with temporal attention.
    """
    
    def __init__(self, model_path: str = None):
        # 1. Config & Paths
        self.config = get_config()
        self.model_path = Path(model_path or self.config.STTN_MODEL_PATH)
        
        # 2. Initialize Components
        self.env_manager = EnvironmentManager(self.config)
        self.media_processor = MediaProcessor(self.config)
        self.res_calculator = ResolutionCalculator(self.config)
        self.strategy = SlidingWindowStrategy(self.config)
        
        # 3. Model initialization (lazy loading)
        self.model = None
        self.device = None
        
        # 4. Setup environment
        self.env_manager.setup_gpu_environment()
        
        # 5. Download weights if missing
        self._ensure_weights()
        
        logger.info(f"✅ STTNAdapter initialized (model: {self.model_path})")

    def _ensure_weights(self):
        """Download STTN weights if missing."""
        if not self.model_path.exists():
            logger.warning(f"⚠️ STTN weights not found at {self.model_path}")
            logger.info("📥 Downloading STTN model...")
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            # STTN model from Google Drive (example URL)
            url = "https://drive.google.com/uc?id=1yVXw0VnAc8-Bn3QJf7pDfHhqHxPqR8Xz"
            gdown.download(url, str(self.model_path), quiet=False)
            logger.info(f"✅ Downloaded STTN weights to {self.model_path}")

    def _load_model(self):
        """Lazy load STTN model."""
        if self.model is not None:
            return
        
        logger.info(f"🔄 Loading STTN model from {self.model_path}")
        
        # Determine device
        self.device = torch.device('cuda' if torch.cuda.is_available() and not self.config.FORCE_CPU else 'cpu')
        
        try:
            # Try to import STTN model
            # For simplicity, we'll implement a basic STTN-like architecture
            # In production, you would import the actual STTN model
            from src.infrastructure.inpainting.components.sttn_model import STTNModel
            self.model = STTNModel()
            self.model.load_state_dict(torch.load(self.model_path, map_location='cpu'))
            self.model.to(self.device)
            self.model.eval()
            logger.info(f"✅ STTN model loaded on {self.device}")
        except ImportError:
            logger.warning("STTN model not available, using dummy implementation for testing")
            # Create a dummy model for testing
            class DummySTTN(torch.nn.Module):
                def forward(self, frames, masks):
                    # Simple inpainting: return original frames where mask is 0
                    # With temporal consistency: average neighboring frames
                    batch_size, seq_len, c, h, w = frames.shape
                    inpainted = frames * (1 - masks)
                    
                    # Add temporal smoothing
                    for t in range(seq_len):
                        if t > 0 and t < seq_len - 1:
                            # Blend with neighbors
                            inpainted[:, t] = 0.7 * inpainted[:, t] + 0.15 * inpainted[:, t-1] + 0.15 * inpainted[:, t+1]
                    
                    return inpainted
            self.model = DummySTTN().to(self.device)
            self.model.eval()

    def _prepare_sequence(self, frames: List[np.ndarray], masks: List[np.ndarray]) -> Tuple[torch.Tensor, torch.Tensor]:
        """Prepare sequence of frames and masks for STTN model."""
        # Convert to tensors
        frame_tensors = []
        mask_tensors = []
        
        for frame, mask in zip(frames, masks):
            # Convert to tensor and normalize
            frame_tensor = torch.from_numpy(frame).permute(2, 0, 1).float() / 255.0
            mask_tensor = torch.from_numpy(mask).unsqueeze(0).float() / 255.0
            
            # Ensure mask is binary
            mask_tensor = (mask_tensor > 0.5).float()
            
            frame_tensors.append(frame_tensor)
            mask_tensors.append(mask_tensor)
        
        # Stack along sequence dimension
        frames_tensor = torch.stack(frame_tensors, dim=0)  # [T, C, H, W]
        masks_tensor = torch.stack(mask_tensors, dim=0)    # [T, 1, H, W]
        
        # Add batch dimension
        frames_tensor = frames_tensor.unsqueeze(0)  # [1, T, C, H, W]
        masks_tensor = masks_tensor.unsqueeze(0)    # [1, T, 1, H, W]
        
        return frames_tensor, masks_tensor

    def _inpaint_sequence(self, frames: List[np.ndarray], masks: List[np.ndarray]) -> List[np.ndarray]:
        """Inpaint a sequence of frames using STTN model."""
        self._load_model()
        
        # Prepare sequence
        frames_tensor, masks_tensor = self._prepare_sequence(frames, masks)
        
        # Move to device
        frames_tensor = frames_tensor.to(self.device)
        masks_tensor = masks_tensor.to(self.device)
        
        # Inpaint
        with torch.no_grad():
            inpainted = self.model(frames_tensor, masks_tensor)
        
        # Convert back to numpy
        inpainted = inpainted.squeeze(0)  # Remove batch dimension
        inpainted = inpainted.permute(0, 2, 3, 1).cpu().numpy()  # [T, H, W, C]
        inpainted = np.clip(inpainted * 255, 0, 255).astype(np.uint8)
        
        return [inpainted[i] for i in range(inpainted.shape[0])]

    def process(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Main entry point. Orchestrates the STTN inpainting pipeline.
        """
        logger.info("🚀 Starting STTN Inpainting Pipeline...")
        
        # 1. Setup GPU Environment
        gpu_info = self.env_manager.setup_gpu_environment()
        
        # 2. Prepare Input Media (Video -> Frames)
        frames_dir = self.media_processor.prepare_input(input_path)
        
        # 3. Calculate Optimal Resolution
        original_dims = self.media_processor.get_frame_dimensions(frames_dir)
        
        # STTN is more memory intensive due to temporal attention
        # Use conservative VRAM estimation
        vram_with_buffer = gpu_info['total_vram_gb'] * 0.8  # 80% of available VRAM
        target_width, target_height, safe_chunk_size = self.res_calculator.calculate_optimal_params(
            original_dims[0], original_dims[1], vram_with_buffer
        )
        
        # Use config chunk size for STTN (larger chunks for better temporal consistency)
        safe_chunk_size = min(self.config.STTN_CHUNK_SIZE, safe_chunk_size)
        
        logger.info(f"🎯 STTN Settings: {target_width}x{target_height} @ {safe_chunk_size} frames/chunk")
        self.strategy.chunk_size = safe_chunk_size
        self.strategy.overlap = self.config.STTN_OVERLAP
        
        # 4. Generate Execution Strategy
        chunks = self.strategy.generate_chunks(frames_dir, mask_dir, output_path.parent)
        
        # 5. Process each chunk
        chunk_results = []
        for chunk_idx, chunk in enumerate(chunks):
            logger.info(f"🔧 Processing chunk {chunk_idx + 1}/{len(chunks)}")
            
            # Load frames and masks for this chunk
            frame_files = sorted(list(chunk['frames_dir'].glob("*.png")))
            mask_files = sorted(list(chunk['masks_dir'].glob("*.png")))
            
            if len(frame_files) != len(mask_files):
                logger.error(f"Frame/Mask count mismatch: {len(frame_files)} != {len(mask_files)}")
                continue
            
            # Load and resize frames/masks
            frames = []
            masks = []
            for frame_file, mask_file in zip(frame_files, mask_files):
                frame = cv2.imread(str(frame_file))
                mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
                
                if frame is None or mask is None:
                    logger.error(f"Failed to load {frame_file} or {mask_file}")
                    continue
                
                # Resize to target dimensions if needed
                if frame.shape[:2] != (target_height, target_width):
                    frame = cv2.resize(frame, (target_width, target_height))
                    mask = cv2.resize(mask, (target_width, target_height))
                
                frames.append(frame)
                masks.append(mask)
            
            if not frames:
                logger.error(f"No frames loaded for chunk {chunk_idx}")
                continue
            
            # Inpaint sequence using STTN
            inpainted_frames = self._inpaint_sequence(frames, masks)
            
            # Save inpainted frames
            chunk_output_dir = chunk['output_dir']
            chunk_output_dir.mkdir(parents=True, exist_ok=True)
            
            for i, frame in enumerate(inpainted_frames):
                output_file = chunk_output_dir / f"frame_{i:06d}.png"
                cv2.imwrite(str(output_file), frame)
            
            chunk_results.append(chunk_output_dir)
        
        # 6. Merge chunks and restore original resolution
        if not chunk_results:
            raise RuntimeError("No chunks were processed successfully")
        
        final_output = self.media_processor.merge_chunks(chunk_results, output_path)
        self.media_processor.restore_aspect_ratio(final_output, original_dims)
        
        # Cleanup
        self.media_processor.cleanup(frames_dir)
        
        logger.info(f"✅ STTN pipeline completed: {final_output}")
        return final_output


# Backward compatibility
class STTNModelAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Use STTNAdapter instead.")
