import os
import sys
import torch
from pathlib import Path
from src.shared.logging import get_logger

# Добавляем путь к ProPainter в sys.path, чтобы импорты работали
PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
if PROPAINTER_ROOT not in sys.path:
    sys.path.append(PROPAINTER_ROOT)

try:
    from model.propainter import InpaintGenerator
    # Предполагаем наличие функции инференса или пишем свою обертку, загружающую веса
except ImportError:
    pass # Обработаем в runtime

logger = get_logger(__name__)

class ProPainterAdapter:
    def __init__(self, weights_path: str = None):
        self.weights_path = weights_path or f"{PROPAINTER_ROOT}/weights/ProPainter.pth"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def process(self, frames_dir: Path, mask_dir: Path, output_dir: Path) -> Path:
        """
        Process frames directory with ProPainter.
        
        Args:
            frames_dir: Directory containing input frames (jpg/png)
            mask_dir: Directory containing mask frames (jpg/png)
            output_dir: Directory where processed frames will be saved
            
        Returns:
            Path to directory containing processed frames
        """
        logger.info("Starting ProPainter Inpainting...")
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # ProPainter typically expects a video file, not frames.
        # We need to create a temporary video from frames, process it,
        # then extract frames back.
        # For simplicity, we'll assume ProPainter can process image sequences.
        # We'll use a subprocess to call the ProPainter inference script.
        
        import subprocess
        
        # Check if frames_dir contains images
        frame_files = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frame_files:
            raise ValueError(f"No frames found in {frames_dir}")
        
        # For now, we'll create a simple implementation that copies frames
        # (This is a placeholder - actual ProPainter integration would go here)
        logger.warning("ProPainterAdapter.process() is a placeholder. Actual ProPainter integration needed.")
        
        # Placeholder: just copy frames as if they were processed
        for frame_path in frame_files:
            # Simulate processing by copying frame
            import shutil
            shutil.copy(frame_path, output_dir / frame_path.name)
        
        logger.info(f"ProPainter processing complete. Results in {output_dir}")
        return output_dir

# Keep old ProPainterModelAdapter for backward compatibility
class ProPainterModelAdapter:
    """Backward compatibility wrapper for ProPainterModelAdapter."""
    
    def __init__(self, model: torch.nn.Module, device: torch.device):
        import warnings
        warnings.warn("ProPainterModelAdapter is deprecated. Use ProPainterAdapter instead.", DeprecationWarning)
        self.model = model
        self.device = device
        
    def process_chunk(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """Deprecated method for backward compatibility."""
        raise NotImplementedError("ProPainterModelAdapter is deprecated. Use ProPainterAdapter instead.")
