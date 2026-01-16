"""
Media processor for ProPainterAdapter.
Handles video/frame operations, aspect ratio, and file management.
"""

import shutil
from typing import List, Tuple, Optional, Dict
from pathlib import Path
from src.core.config import AppConfig


class MediaProcessor:
    """Handles media operations for ProPainter processing."""
    
    def __init__(self, config: AppConfig):
        self.config = config
    
    def prepare_input(self, input_path: Path) -> Path:
        """
        Prepare input for processing (video or frames).
        
        Args:
            input_path: Path to video file or frames directory
            
        Returns:
            Path to prepared frames directory
        """
        if input_path.is_dir():
            # Already a frames directory
            return input_path
        else:
            # Video file, extract frames
            import tempfile
            temp_dir = Path(tempfile.mkdtemp(prefix="propainter_frames_"))
            frames = self.extract_frames_from_video(input_path, temp_dir)
            return temp_dir
    
    def extract_frames_from_video(self, video_path: Path, output_dir: Path) -> List[Path]:
        """
        Extract frames from video using ffmpeg.
        
        Args:
            video_path: Path to video file
            output_dir: Directory to save extracted frames
            
        Returns:
            List of extracted frame paths
        """
        import subprocess
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Use ffmpeg to extract frames
        frame_pattern = output_dir / "frame_%08d.png"
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vsync", "0",  # preserve frame timestamps
            "-q:v", "2",    # quality
            str(frame_pattern)
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to extract frames: {e.stderr}")
        
        # Collect frames
        frames = sorted(output_dir.glob("frame_*.png"))
        if not frames:
            raise RuntimeError(f"No frames extracted from {video_path}")
        
        return frames
    
    def validate_and_restore_aspect_ratio(self, frames: List[Path], 
                                         original_dims: Tuple[int, int]) -> None:
        """
        Validate and restore aspect ratio of processed frames.
        
        Args:
            frames: List of frame paths to validate
            original_dims: Original (width, height) dimensions
        """
        from PIL import Image
        import numpy as np
        
        if not frames:
            return
        
        # Check first frame dimensions
        with Image.open(frames[0]) as img:
            processed_width, processed_height = img.size
        
        original_width, original_height = original_dims
        
        # If dimensions match, nothing to do
        if processed_width == original_width and processed_height == original_height:
            return
        
        # Check if dimensions are swapped (common ProPainter bug)
        if processed_width == original_height and processed_height == original_width:
            # Rotate 90 degrees
            for frame_path in frames:
                with Image.open(frame_path) as img:
                    rotated = img.rotate(90, expand=True)
                    rotated.save(frame_path)
            return
        
        # If dimensions differ but not swapped, resize to original
        for frame_path in frames:
            with Image.open(frame_path) as img:
                if img.size != (original_width, original_height):
                    resized = img.resize((original_width, original_height), Image.Resampling.LANCZOS)
                    resized.save(frame_path)
    
    def merge_chunks(self, chunk_results: Dict[str, Path], output_dir: Path) -> Path:
        """
        Merge chunk results into final output.
        
        Args:
            chunk_results: Dictionary mapping frame names to chunk result paths
            output_dir: Directory to save merged frames
            
        Returns:
            Path to merged output directory
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for frame_name, chunk_path in chunk_results.items():
            dest = output_dir / frame_name
            if chunk_path.exists():
                shutil.copy2(chunk_path, dest)
        
        return output_dir
    
    def get_frame_dimensions(self, frames_dir: Path) -> Tuple[int, int]:
        """
        Get dimensions of first frame in directory.
        
        Args:
            frames_dir: Directory containing frames
            
        Returns:
            (width, height) tuple
        """
        from PIL import Image
        frames = sorted(frames_dir.glob("*.png"))
        if not frames:
            raise ValueError(f"No PNG frames found in {frames_dir}")
        with Image.open(frames[0]) as img:
            return img.size
    
    def restore_aspect_ratio(self, frames_dir: Path, original_dims: Tuple[int, int]) -> None:
        """
        Restore original aspect ratio to processed frames.
        
        Args:
            frames_dir: Directory containing processed frames
            original_dims: Original (width, height) dimensions
        """
        frames = sorted(frames_dir.glob("*.png"))
        if not frames:
            return
        self.validate_and_restore_aspect_ratio(frames, original_dims)
    
    def cleanup(self, temp_dir: Path) -> None:
        """
        Clean up temporary directory.
        
        Args:
            temp_dir: Temporary directory to remove
        """
        if temp_dir.exists() and temp_dir.is_dir():
            shutil.rmtree(temp_dir, ignore_errors=True)
