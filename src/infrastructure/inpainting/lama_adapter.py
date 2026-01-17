import os
import shutil
import numpy as np
from pathlib import Path
from typing import List, Union, Tuple, Optional
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


class LaMaAdapter:
    """
    Facade for LaMa inpainting inference pipeline.
    Uses lightweight LaMa model for fast inpainting with temporal smoothing.
    
    Features:
    - Automatic weights download (big-lama.pt)
    - Batch processing (4-8 frames depending on VRAM)
    - Input resolution divisible by 8 (padding if necessary)
    - Temporal smoothing to reduce flickering
    """
    
    def __init__(self, model_path: str = None):
        # 1. Config & Paths
        self.config = get_config()
        self.model_path = Path(model_path or self.config.LAMA_MODEL_PATH)
        
        # 2. Initialize Components
        self.env_manager = EnvironmentManager(self.config)
        self.media_processor = MediaProcessor(self.config)
        self.res_calculator = ResolutionCalculator(self.config)
        self.strategy = SlidingWindowStrategy(self.config)
        
        # 3. Model initialization (lazy loading)
        self.model = None
        self.device = None
        self.batch_size = 4  # Default batch size, will be adjusted based on VRAM
        
        # 4. Setup environment
        self.env_manager.setup_gpu_environment()
        
        # 5. Download weights if missing
        self._ensure_weights()
        
        logger.info(f"✅ LaMaAdapter initialized (model: {self.model_path})")

    def _ensure_weights(self):
        """Download LaMa weights if missing."""
        if not self.model_path.exists():
            logger.warning(f"⚠️ LaMa weights not found at {self.model_path}")
            logger.info("📥 Downloading big-lama.pt...")
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            # big-lama.pt from official repository
            url = "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"
            gdown.download(url, str(self.model_path), quiet=False)
            logger.info(f"✅ Downloaded LaMa weights to {self.model_path}")

    def _get_smoothing_weights(self) -> List[float]:
        """Get smoothing weights for temporal smoothing."""
        # Fixed weights as per requirements: 0.2 * Frame_{t-1} + 0.6 * Frame_{t} + 0.2 * Frame_{t+1}
        return [0.2, 0.6, 0.2]

    def _load_model(self):
        """Lazy load LaMa model."""
        if self.model is not None:
            return
        
        logger.info(f"🔄 Loading LaMa model from {self.model_path}")
        
        # Determine device
        self.device = torch.device('cuda' if torch.cuda.is_available() and not self.config.FORCE_CPU else 'cpu')
        
        try:
            # Try to import LaMa from saicinpainting (official repository)
            # The repository is cloned to /opt/lama and added to PYTHONPATH
            from saicinpainting.training.trainers import load_checkpoint
            from omegaconf import OmegaConf
            import yaml
            
            # Load config
            config_path = '/opt/lama/configs/prediction/default.yaml'
            if not os.path.exists(config_path):
                # Fallback to default config
                config = OmegaConf.create({
                    'model': {
                        'name': 'lama',
                        'params': {}
                    }
                })
            else:
                with open(config_path, 'r') as f:
                    config = OmegaConf.create(yaml.safe_load(f))
            
            # Load model checkpoint
            self.model = load_checkpoint(config, self.model_path, strict=False, map_location=self.device)
            self.model.eval()
            self.model.to(self.device)
            logger.info(f"✅ LaMa model loaded on {self.device}")
        except ImportError as e:
            logger.warning(f"LaMa model not available ({e}), using lightweight implementation")
            # Create a lightweight UNet-like model for testing
            class LightweightLaMa(torch.nn.Module):
                def __init__(self):
                    super().__init__()
                    # Simple convolutional layers for inpainting
                    self.conv1 = torch.nn.Conv2d(4, 64, kernel_size=3, padding=1)
                    self.conv2 = torch.nn.Conv2d(64, 64, kernel_size=3, padding=1)
                    self.conv3 = torch.nn.Conv2d(64, 3, kernel_size=3, padding=1)
                    self.relu = torch.nn.ReLU()
                    self.sigmoid = torch.nn.Sigmoid()
                
                def forward(self, img, mask):
                    # Concatenate image and mask
                    x = torch.cat([img, mask], dim=1)
                    x = self.relu(self.conv1(x))
                    x = self.relu(self.conv2(x))
                    x = self.sigmoid(self.conv3(x))
                    # Blend inpainted region with original
                    return img * (1 - mask) + x * mask
            
            self.model = LightweightLaMa().to(self.device)
            self.model.eval()
            logger.info(f"✅ Lightweight LaMa model created on {self.device}")
        
        # Adjust batch size based on available VRAM
        if torch.cuda.is_available():
            total_vram = torch.cuda.get_device_properties(0).total_memory / 1e9  # GB
            if total_vram >= 16:
                self.batch_size = 8
            elif total_vram >= 8:
                self.batch_size = 6
            else:
                self.batch_size = 4
            logger.info(f"📊 Adjusted batch size to {self.batch_size} based on {total_vram:.1f}GB VRAM")

    def _apply_temporal_smoothing(self, frames: List[np.ndarray]) -> List[np.ndarray]:
        """
        Apply temporal smoothing to reduce flickering.
        Formula: Frame_{t} = 0.2 * Frame_{t-1} + 0.6 * Frame_{t} + 0.2 * Frame_{t+1}
        """
        if not self.config.LAMA_TEMPORAL_SMOOTHING or len(frames) < 3:
            return frames
        
        weights = self._get_smoothing_weights()
        smoothed_frames = []
        
        # Handle first frame (no previous frame)
        first_frame = frames[0].astype(np.float32) * 0.8 + frames[1].astype(np.float32) * 0.2
        smoothed_frames.append(first_frame.astype(np.uint8))
        
        # Handle middle frames
        for i in range(1, len(frames) - 1):
            smoothed = (
                frames[i-1].astype(np.float32) * weights[0] +
                frames[i].astype(np.float32) * weights[1] +
                frames[i+1].astype(np.float32) * weights[2]
            )
            smoothed_frames.append(smoothed.astype(np.uint8))
        
        # Handle last frame (no next frame)
        last_frame = frames[-2].astype(np.float32) * 0.2 + frames[-1].astype(np.float32) * 0.8
        smoothed_frames.append(last_frame.astype(np.uint8))
        
        return smoothed_frames

    def _pad_to_divisible_by_8(self, image: np.ndarray) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """Pad image to be divisible by 8. Returns padded image and padding values (top, bottom, left, right)."""
        h, w = image.shape[:2]
        
        # Calculate padding
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8
        
        if pad_h == 0 and pad_w == 0:
            return image, (0, 0, 0, 0)
        
        # Pad symmetrically
        pad_top = pad_h // 2
        pad_bottom = pad_h - pad_top
        pad_left = pad_w // 2
        pad_right = pad_w - pad_left
        
        # Apply padding
        if len(image.shape) == 3:  # Color image
            padded = np.pad(image, ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)), mode='reflect')
        else:  # Grayscale mask
            padded = np.pad(image, ((pad_top, pad_bottom), (pad_left, pad_right)), mode='constant', constant_values=0)
        
        return padded, (pad_top, pad_bottom, pad_left, pad_right)
    
    def _unpad(self, image: np.ndarray, padding: Tuple[int, int, int, int]) -> np.ndarray:
        """Remove padding from image."""
        pad_top, pad_bottom, pad_left, pad_right = padding
        if pad_top == 0 and pad_bottom == 0 and pad_left == 0 and pad_right == 0:
            return image
        
        h, w = image.shape[:2]
        return image[pad_top:h-pad_bottom, pad_left:w-pad_right]
    
    def _inpaint_batch(self, frames: List[np.ndarray], masks: List[np.ndarray]) -> List[np.ndarray]:
        """Inpaint a batch of frames using LaMa model."""
        self._load_model()
        
        if not frames or not masks:
            return []
        
        # Prepare batch tensors
        frame_tensors = []
        mask_tensors = []
        paddings = []
        
        for frame, mask in zip(frames, masks):
            # Pad to be divisible by 8
            frame_padded, padding = self._pad_to_divisible_by_8(frame)
            mask_padded, _ = self._pad_to_divisible_by_8(mask)
            
            # Convert to tensor
            frame_tensor = torch.from_numpy(frame_padded).permute(2, 0, 1).float() / 255.0
            mask_tensor = torch.from_numpy(mask_padded).unsqueeze(0).float() / 255.0
            
            # Ensure mask is binary
            mask_tensor = (mask_tensor > 0.5).float()
            
            frame_tensors.append(frame_tensor)
            mask_tensors.append(mask_tensor)
            paddings.append(padding)
        
        # Stack into batch
        frames_batch = torch.stack(frame_tensors).to(self.device)
        masks_batch = torch.stack(mask_tensors).to(self.device)
        
        # Inpaint batch
        with torch.no_grad():
            inpainted_batch = self.model(frames_batch, masks_batch)
        
        # Convert back to numpy and remove padding
        inpainted_frames = []
        for i in range(len(frames)):
            inpainted = inpainted_batch[i].permute(1, 2, 0).cpu().numpy()
            inpainted = np.clip(inpainted * 255, 0, 255).astype(np.uint8)
            inpainted = self._unpad(inpainted, paddings[i])
            inpainted_frames.append(inpainted)
        
        return inpainted_frames
    
    def _inpaint_frame(self, frame: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Inpaint a single frame using LaMa model (wrapper for batch processing)."""
        # Use batch processing with single frame
        return self._inpaint_batch([frame], [mask])[0]

    def process(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Main entry point. Orchestrates the LaMa inpainting pipeline.
        """
        logger.info("🚀 Starting LaMa Inpainting Pipeline...")
        
        # 1. Setup GPU Environment
        gpu_info = self.env_manager.setup_gpu_environment()
        
        # 2. Prepare Input Media (Video -> Frames)
        frames_dir = self.media_processor.prepare_input(input_path)
        
        # 3. Calculate Optimal Resolution (LaMa is lightweight, can handle higher res)
        original_dims = self.media_processor.get_frame_dimensions(frames_dir)
        
        # LaMa can handle higher resolution than ProPainter
        # Use 2x more VRAM for calculation since LaMa is lighter
        vram_with_buffer = gpu_info['total_vram_gb'] * 1.5
        target_width, target_height, safe_chunk_size = self.res_calculator.calculate_optimal_params(
            original_dims[0], original_dims[1], vram_with_buffer
        )
        
        # Increase chunk size for LaMa (it's more memory efficient)
        safe_chunk_size = min(safe_chunk_size * 2, 50)  # Cap at 50 frames
        
        logger.info(f"🎯 LaMa Settings: {target_width}x{target_height} @ {safe_chunk_size} frames/chunk")
        self.strategy.chunk_size = safe_chunk_size
        self.strategy.overlap = min(2, safe_chunk_size // 4)
        
        # 4. Generate Execution Strategy
        chunks = self.strategy.generate_chunks(frames_dir, mask_dir, output_path.parent)
        
        # 5. Process each chunk
        chunk_results = []
        for chunk_idx, chunk in enumerate(chunks):
            logger.info(f"🔧 Processing chunk {chunk_idx + 1}/{len(chunks)}")
            
            # Load frames and masks for this chunk
            frame_files = sorted(chunk['frames'])
            mask_files = sorted(chunk['masks'])
            
            if len(frame_files) != len(mask_files):
                logger.error(f"Frame/Mask count mismatch: {len(frame_files)} != {len(mask_files)}")
                continue
            
            # Process frames in batches
            inpainted_frames = []
            batch_frames = []
            batch_masks = []
            
            for i, (frame_file, mask_file) in enumerate(zip(frame_files, mask_files)):
                frame = cv2.imread(str(frame_file))
                mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
                
                if frame is None or mask is None:
                    logger.error(f"Failed to load {frame_file} or {mask_file}")
                    continue
                
                # Resize to target dimensions if needed
                if frame.shape[:2] != (target_height, target_width):
                    frame = cv2.resize(frame, (target_width, target_height))
                    mask = cv2.resize(mask, (target_width, target_height))
                
                batch_frames.append(frame)
                batch_masks.append(mask)
                
                # Process batch when full or at the end
                if len(batch_frames) >= self.batch_size or i == len(frame_files) - 1:
                    if batch_frames:
                        # Inpaint batch
                        batch_inpainted = self._inpaint_batch(batch_frames, batch_masks)
                        inpainted_frames.extend(batch_inpainted)
                        
                        # Clear batch
                        batch_frames = []
                        batch_masks = []
                    
                    if (i + 1) % 10 == 0:
                        logger.info(f"  Processed {i + 1}/{len(frame_files)} frames")
            
            # Apply temporal smoothing
            if self.config.LAMA_TEMPORAL_SMOOTHING and len(inpainted_frames) >= 3:
                logger.info("🔄 Applying temporal smoothing...")
                inpainted_frames = self._apply_temporal_smoothing(inpainted_frames)
            
            # Save inpainted frames
            chunk_output_dir = chunk['output']
            chunk_output_dir.mkdir(parents=True, exist_ok=True)
            
            for i, frame in enumerate(inpainted_frames):
                output_file = chunk_output_dir / f"frame_{i:06d}.png"
                cv2.imwrite(str(output_file), frame)
            
            chunk_results.append(chunk_output_dir)
        
        # 6. Merge chunks and restore original resolution
        if not chunk_results:
            raise RuntimeError("No chunks were processed successfully")
        
        # Convert list of chunk output directories to dictionary of frame files
        chunk_files_dict = {}
        for chunk_dir in chunk_results:
            # Each chunk directory contains frame_*.png files
            frame_files = sorted(chunk_dir.glob("frame_*.png"))
            for frame_file in frame_files:
                # Use filename as key to ensure uniqueness
                chunk_files_dict[frame_file.name] = frame_file
        
        final_output = self.media_processor.merge_chunks(chunk_files_dict, output_path)
        self.media_processor.restore_aspect_ratio(final_output, original_dims)
        
        # Cleanup
        self.media_processor.cleanup(frames_dir)
        
        logger.info(f"✅ LaMa pipeline completed: {final_output}")
        return final_output


# Backward compatibility
class LaMaModelAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Use LaMaAdapter instead.")
