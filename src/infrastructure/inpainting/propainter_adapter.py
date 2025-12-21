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
        # Sliding Window settings for OOM protection (Exit code -9)
        self.CHUNK_SIZE = 40    # Process 40 frames at a time
        self.OVERLAP = 10       # Overlap for seamless stitching

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
        """
        Process frames directory with ProPainter using Sliding Window strategy to prevent OOM.
        """
        logger.info(f"Processing frames directory: {frames_dir}")
        
        if not frames_dir.exists():
            raise FileNotFoundError(f"Frames dir not found: {frames_dir}")
        if not mask_dir.exists():
            raise FileNotFoundError(f"Masks dir not found: {mask_dir}")

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Get list of all frames
        all_frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        total_frames = len(all_frames)
        
        logger.info(f"Preparing ProPainter for {total_frames} frames...")
        
        # If frames are few, run directly (Fast Path)
        if total_frames <= self.CHUNK_SIZE:
            return self._run_inference_subprocess(frames_dir, mask_dir, output_dir)
            
        # 2. Sliding Window Logic (Slow Path but Safe)
        logger.info(f"Video too long ({total_frames} > {self.CHUNK_SIZE}). Using Sliding Window processing.")
        
        # Create temporary directory for chunks
        import math
        chunk_base_dir = output_dir.parent / "propainter_chunks"
        if chunk_base_dir.exists(): 
            shutil.rmtree(chunk_base_dir)
        chunk_base_dir.mkdir()
        
        # Calculate number of chunks
        # Step = Size - Overlap
        step = self.CHUNK_SIZE - self.OVERLAP
        num_chunks = math.ceil((total_frames - self.OVERLAP) / step)
        
        processed_frames_map = {}  # frame_name -> path_to_processed_chunk_file

        for i in range(num_chunks):
            start_idx = i * step
            end_idx = min(start_idx + self.CHUNK_SIZE, total_frames)
            
            # Adjust last chunk to be full (if possible)
            if end_idx == total_frames:
                start_idx = max(0, total_frames - self.CHUNK_SIZE)
                
            chunk_frames = all_frames[start_idx:end_idx]
            chunk_id = f"chunk_{i:03d}"
            
            logger.info(f"Processing Chunk {i+1}/{num_chunks}: Frames {start_idx}-{end_idx} ({len(chunk_frames)})")
            
            # Prepare chunk directories
            c_input = chunk_base_dir / chunk_id / "frames"
            c_mask = chunk_base_dir / chunk_id / "masks"
            c_output = chunk_base_dir / chunk_id / "output"
            c_input.mkdir(parents=True)
            c_mask.mkdir(parents=True)
            
            # Copy files
            for f in chunk_frames:
                shutil.copy(f, c_input / f.name)
                # Mask should have the same name
                mask_src = mask_dir / f.name
                if mask_src.exists():
                    shutil.copy(mask_src, c_mask / f.name)
            
            # RUN INFERENCE ON CHUNK
            self._run_inference_subprocess(c_input, c_mask, c_output)
            
            # Collect results (Merging Logic)
            # ProPainter usually puts results in c_output/inpaint_out or just c_output
            # Find where the result is
            results = list(c_output.glob("**/*.png")) + list(c_output.glob("**/*.jpg"))
            
            for res_file in results:
                frame_name = res_file.name
                # Merging logic:
                # If this frame was already processed (in previous chunk), we overwrite it,
                # ONLY if we are in the "middle" of current chunk (where quality is higher),
                # not on the edge. But for MVP just overwrite with new data.
                processed_frames_map[frame_name] = res_file

        # 3. Final assembly
        logger.info("Merging chunks...")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        final_count = 0
        for fname in sorted(processed_frames_map.keys()):
            src = processed_frames_map[fname]
            shutil.copy(src, output_dir / fname)
            final_count += 1
            
        # Cleanup
        if chunk_base_dir.exists(): 
            shutil.rmtree(chunk_base_dir)
        
        logger.info(f"✅ Merged {final_count} frames successfully.")
        return output_dir

    def _run_inference_subprocess(self, video_path: Path, mask_path: Path, output_path: Path) -> Path:
        """Helper to run the actual CLI command"""
        cmd = [
            "python3", str(self.inference_script),
            "--video", str(video_path),
            "--mask", str(mask_path),
            "--output", str(output_path),
            "--width", "960", "--height", "540" 
        ]
        
        try:
            subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=str(self.root),
                check=True
            )
            
            # Проверка, что файлы создались (ProPainter иногда создает подпапку inpaint_out)
            # Если создалась подпапка, перемещаем файлы на уровень выше
            subfolder = output_path / "inpaint_out"
            if subfolder.exists():
                for f in subfolder.iterdir():
                    shutil.move(str(f), str(output_path / f.name))
                subfolder.rmdir()
                
            return output_path

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ ProPainter Subprocess Crashed!")
            logger.error(f"STDERR: {e.stderr}")
            # Пытаемся освободить память перед падением
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
