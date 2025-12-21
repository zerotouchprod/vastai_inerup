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

    def process(self, input_path: Path, mask_dir: Path, output_path: Path) -> Path:
        """
        Process input with ProPainter.
        
        Args:
            input_path: Can be either:
                - Path to video file (.mp4, .avi, etc.)
                - Path to directory containing frames (jpg/png)
            mask_dir: Directory containing mask frames (jpg/png)
            output_path: Output path (file if input is video, directory if input is frames)
            
        Returns:
            Path to output (file or directory)
        """
        logger.info("Starting ProPainter Inpainting...")
        
        # Check if input_path is a directory (frames) or file (video)
        if input_path.is_dir():
            # Frames directory mode (used by StreamingSubtitleRemoverService)
            return self._process_frames_dir(input_path, mask_dir, output_path)
        else:
            # Video file mode (used by SubtitleRemoverService)
            return self._process_video_file(input_path, mask_dir, output_path)
    
    def _process_video_file(self, video_path: Path, mask_dir: Path, output_path: Path) -> Path:
        """Process video file with ProPainter."""
        logger.info(f"Processing video file: {video_path}")
        
        # Original implementation for video files
        import subprocess
        
        cmd = [
            "python", f"{PROPAINTER_ROOT}/inference_propainter.py",
            "--video", str(video_path),
            "--mask", str(mask_dir),
            "--output", str(output_path.parent),
            "--save_format", "mp4"
        ]
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            logger.error(f"ProPainter failed: {process.stderr}")
            raise RuntimeError("ProPainter execution failed")
            
        logger.info("ProPainter finished successfully.")
        return output_path
    
    def _process_frames_dir(self, frames_dir: Path, mask_dir: Path, output_dir: Path) -> Path:
        """Process frames directory with ProPainter."""
        logger.info(f"Processing frames directory: {frames_dir}")
        
        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if frames_dir contains images
        frame_files = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frame_files:
            raise ValueError(f"No frames found in {frames_dir}")
        
        # For now, we'll create a simple implementation that copies frames
        # (This is a placeholder - actual ProPainter integration would go here)
        logger.warning("ProPainterAdapter._process_frames_dir() is a placeholder. Actual ProPainter integration needed.")
        
        # Placeholder: just copy frames as if they were processed
        import shutil
        for frame_path in frame_files:
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
