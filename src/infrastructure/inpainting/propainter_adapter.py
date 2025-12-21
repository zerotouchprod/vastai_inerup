import os
import shutil
import subprocess
import sys
import torch
from pathlib import Path
from src.shared.logging import get_logger

logger = get_logger(__name__)

class ProPainterAdapter:
    def __init__(self, propainter_root: str = None):
        self.root = Path(propainter_root or os.getenv("PROPAINTER_ROOT", "/opt/ProPainter"))
        self.inference_script = self.root / "inference_propainter.py"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def process(self, input_path, mask_dir: Path, output_path: Path) -> Path:
        """
        Process input with ProPainter.
        
        Args:
            input_path: Can be either:
                - Path to video file (.mp4, .avi, etc.)
                - Path to directory containing frames (jpg/png)
                - List of Path objects (frame paths)
            mask_dir: Directory containing mask frames (jpg/png)
            output_path: Output path (file if input is video, directory if input is frames)
            
        Returns:
            Path to output (file or directory)
        """
        logger.info("Starting ProPainter Inpainting...")
        
        # Handle list of frame paths
        if isinstance(input_path, list):
            # Create temporary directory for frames
            import tempfile
            with tempfile.TemporaryDirectory(prefix="propainter_frames_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                # Copy frames to temporary directory
                for i, frame_path in enumerate(input_path):
                    if isinstance(frame_path, Path):
                        shutil.copy(frame_path, tmp_path / f"frame_{i:06d}{frame_path.suffix}")
                    else:
                        shutil.copy(Path(frame_path), tmp_path / f"frame_{i:06d}{Path(frame_path).suffix}")
                # Process as frames directory
                return self._process_frames_dir(tmp_path, mask_dir, output_path)
        
        # Convert to Path if it's a string
        if not isinstance(input_path, Path):
            input_path = Path(input_path)
        
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
        
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not mask_dir.exists():
            raise FileNotFoundError(f"Masks dir not found: {mask_dir}")

        cmd = [
            "python3", str(self.inference_script),
            "--video", str(video_path),
            "--mask", str(mask_dir),
            "--output", str(output_path.parent),
            "--save_format", "mp4",
            "--width", "960", "--height", "540"  # Resize for stability/VRAM
        ]
        
        logger.info(f"⚡ Executing ProPainter: {' '.join(cmd)}")
        
        try:
            if not self.inference_script.exists():
                raise FileNotFoundError(f"ProPainter script not found at {self.inference_script}")

            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=str(self.root),
                check=True
            )
            
            # Verify results exist
            results = list(output_path.parent.glob("**/*.mp4")) + list(output_path.parent.glob("**/*.avi"))
            if not results:
                logger.error(f"ProPainter finished but no output files found in {output_path.parent}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError("ProPainter produced no output")
                
            logger.info(f"✅ ProPainter completed. Generated output video.")
            return output_path

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ ProPainter Crashed!")
            logger.error(f"STDERR: {e.stderr}")
            raise RuntimeError(f"ProPainter execution failed with code {e.returncode}")
    
    def _process_frames_dir(self, frames_dir: Path, mask_dir: Path, output_dir: Path) -> Path:
        """Process frames directory with ProPainter."""
        logger.info(f"Processing frames directory: {frames_dir}")
        
        if not frames_dir.exists():
            raise FileNotFoundError(f"Frames dir not found: {frames_dir}")
        if not mask_dir.exists():
            raise FileNotFoundError(f"Masks dir not found: {mask_dir}")

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            "python3", str(self.inference_script),
            "--video", str(frames_dir),
            "--mask", str(mask_dir),
            "--output", str(output_dir),
            "--width", "960", "--height", "540"  # Resize for stability/VRAM
        ]
        
        logger.info(f"⚡ Executing ProPainter: {' '.join(cmd)}")
        
        try:
            if not self.inference_script.exists():
                raise FileNotFoundError(f"ProPainter script not found at {self.inference_script}")

            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=str(self.root),
                check=True
            )
            
            # ProPainter typically outputs to {output_dir}/inpaint_out or similar. 
            # We need to find where it actually put the images.
            # Usually it mirrors the input folder name or creates 'results'.
            # For now, we assume it dumps into output_dir directly or a subfolder.
            
            # Verify results exist
            results = list(output_dir.glob("**/*.jpg")) + list(output_dir.glob("**/*.png"))
            if not results:
                logger.error(f"ProPainter finished but no output files found in {output_dir}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError("ProPainter produced no output")
                
            logger.info(f"✅ ProPainter completed. Generated {len(results)} frames.")
            return output_dir

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ ProPainter Crashed!")
            logger.error(f"STDERR: {e.stderr}")
            raise RuntimeError(f"ProPainter execution failed with code {e.returncode}")

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
