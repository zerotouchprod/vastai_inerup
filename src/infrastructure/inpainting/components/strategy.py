"""
Sliding window strategy for ProPainterAdapter.
Handles chunk generation, overlap calculation, and parallel processing.
"""

from typing import List, Tuple, Dict
from pathlib import Path
from src.core.config import AppConfig


class SlidingWindowStrategy:
    """Manages sliding window chunking strategy for long videos."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.chunk_size = config.MAX_FRAMES_PER_CHUNK
        self.overlap = config.PROPAINTER_OVERLAP
    
    def generate_chunks(self, frames_dir: Path, mask_dir: Path, output_parent: Path) -> List[Dict]:
        """
        Generate chunks for sliding window processing.
        
        Args:
            frames_dir: Directory containing input frames
            mask_dir: Directory containing mask frames
            output_parent: Parent directory for chunk outputs
            
        Returns:
            List of chunk dictionaries with 'id', 'frames', 'masks', 'output'
        """
        import os
        frames = sorted(frames_dir.glob("*.png"))
        masks = sorted(mask_dir.glob("*.png"))
        total_frames = len(frames)
        
        if total_frames <= self.chunk_size:
            # Single chunk covering all frames
            chunk_id = 0
            chunk_dir = output_parent / f"chunk_{chunk_id:03d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            return [{
                'id': chunk_id,
                'frames': frames,
                'masks': masks,
                'output': chunk_dir / "output",
                'frame_indices': (0, total_frames)
            }]
        
        step = self.chunk_size - self.overlap
        num_chunks = (total_frames - self.overlap + step - 1) // step  # ceil division
        
        chunks = []
        for i in range(num_chunks):
            start_idx = i * step
            end_idx = min(start_idx + self.chunk_size, total_frames)
            
            # Adjust last chunk to ensure it has full chunk_size if possible
            if end_idx == total_frames:
                start_idx = max(0, total_frames - self.chunk_size)
            
            chunk_id = i
            chunk_dir = output_parent / f"chunk_{chunk_id:03d}"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            
            # Create symlinks or copy frames/masks for this chunk
            chunk_frames_dir = chunk_dir / "frames"
            chunk_masks_dir = chunk_dir / "masks"
            chunk_frames_dir.mkdir(exist_ok=True)
            chunk_masks_dir.mkdir(exist_ok=True)
            
            for idx in range(start_idx, end_idx):
                if idx < len(frames):
                    os.symlink(frames[idx], chunk_frames_dir / frames[idx].name)
                if idx < len(masks):
                    os.symlink(masks[idx], chunk_masks_dir / masks[idx].name)
            
            chunks.append({
                'id': chunk_id,
                'frames': list(chunk_frames_dir.iterdir()),
                'masks': list(chunk_masks_dir.iterdir()),
                'output': chunk_dir / "output",
                'frame_indices': (start_idx, end_idx)
            })
        
        return chunks
    
    def needs_chunking(self, total_frames: int) -> bool:
        """
        Determine if chunking is needed.
        
        Args:
            total_frames: Total number of frames
            
        Returns:
            True if chunking is required
        """
        return total_frames > self.chunk_size
    
    def get_chunk_paths(self, base_dir: Path, chunk_id: int) -> Dict[str, Path]:
        """
        Generate paths for chunk directories.
        
        Args:
            base_dir: Base directory for chunks
            chunk_id: Chunk identifier
            
        Returns:
            Dictionary with 'input', 'mask', 'output' paths
        """
        chunk_dir = base_dir / f"chunk_{chunk_id:03d}"
        return {
            'input': chunk_dir / "frames",
            'mask': chunk_dir / "masks",
            'output': chunk_dir / "output",
        }
