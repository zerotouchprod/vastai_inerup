"""
Inference runner for ProPainterAdapter.
Handles CLI command construction, subprocess execution, and error handling.
"""

import subprocess
from typing import List, Optional, Dict
from pathlib import Path
from src.core.config import AppConfig
from src.shared.logging import get_logger

logger = get_logger(__name__)


class InferenceRunner:
    """Executes ProPainter inference commands."""
    
    def __init__(self, config: AppConfig, propainter_root: Path):
        self.config = config
        self.propainter_root = propainter_root
        self.inference_script = propainter_root / "inference_propainter.py"
    
    def build_command(self, video_path: Path, mask_path: Path, output_path: Path,
                     target_width: int, target_height: int, gpu_id: Optional[int] = None) -> List[str]:
        """
        Build CLI command for ProPainter inference.
        
        Args:
            video_path: Path to video or frames directory
            mask_path: Path to masks directory
            output_path: Path to output directory
            target_width: Target frame width
            target_height: Target frame height
            gpu_id: GPU ID to use (for multi-GPU)
            
        Returns:
            List of command arguments
        """
        cmd = [
            "python3", str(self.inference_script),
            "--video", str(video_path),
            "--mask", str(mask_path),
            "--output", str(output_path),
            "--width", str(target_width),
            "--height", str(target_height),
            "--save_frames"  # Try to get individual frames instead of video
        ]
        return cmd
    
    def execute_command(self, command: List[str], gpu_id: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Execute ProPainter command.
        
        Args:
            command: Command to execute
            gpu_id: GPU ID to use (for multi-GPU)
            
        Returns:
            CompletedProcess object
        """
        import os
        env = os.environ.copy()
        if gpu_id is not None:
            env['CUDA_VISIBLE_DEVICES'] = str(gpu_id)
        
        # OPTIMIZED MEMORY MANAGEMENT settings
        env['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:128,garbage_collection_threshold:0.6,expandable_segments:True'
        
        logger.info(f"Executing ProPainter command: {' '.join(command)}")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(self.propainter_root),
                env=env,
                check=True
            )
            logger.info(f"ProPainter command succeeded with return code {result.returncode}")
            if result.stdout:
                # Log first few lines of stdout to see progress
                lines = result.stdout.strip().split('\n')
                for line in lines[:10]:  # log first 10 lines
                    if line.strip():
                        logger.info(f"ProPainter: {line[:200]}")
                if len(lines) > 10:
                    logger.info(f"... and {len(lines) - 10} more lines")
            if result.stderr:
                # Log stderr as warning
                lines = result.stderr.strip().split('\n')
                for line in lines[:5]:
                    if line.strip():
                        logger.warning(f"ProPainter stderr: {line[:200]}")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"ProPainter command failed with code {e.returncode}")
            if e.stdout:
                logger.debug(f"ProPainter stdout: {e.stdout[:500]}")
            if e.stderr:
                logger.error(f"ProPainter stderr: {e.stderr[:500]}")
            # If --save_frames fails, try without it
            if "--save_frames" in command:
                logger.info("Retrying without --save_frames flag")
                # Remove --save_frames and retry
                new_command = [arg for arg in command if arg != "--save_frames"]
                try:
                    result = subprocess.run(
                        new_command,
                        capture_output=True,
                        text=True,
                        cwd=str(self.propainter_root),
                        env=env,
                        check=True
                    )
                    logger.info(f"Retry succeeded with return code {result.returncode}")
                    return result
                except subprocess.CalledProcessError as e2:
                    self.handle_inference_error(e2)
                    raise
            else:
                self.handle_inference_error(e)
                raise
    
    def handle_inference_error(self, error: subprocess.CalledProcessError) -> None:
        """
        Handle inference errors with appropriate logging and fallbacks.
        
        Args:
            error: CalledProcessError from subprocess execution
        """
        # Log error details (in real implementation would use logger)
        stderr = error.stderr if error.stderr else ""
        stdout = error.stdout if error.stdout else ""
        
        # If stderr/stdout are bytes, decode them
        if isinstance(stderr, bytes):
            stderr = stderr.decode('utf-8', errors='ignore')
        if isinstance(stdout, bytes):
            stdout = stdout.decode('utf-8', errors='ignore')
        
        # Check for OOM errors
        if "out of memory" in stderr.lower() or "oom" in stderr.lower():
            raise RuntimeError(f"ProPainter OOM error: {stderr[:500]}")
        
        # Check for CUDA errors
        if "cuda error" in stderr.lower():
            raise RuntimeError(f"CUDA error: {stderr[:500]}")
        
        # Generic error
        raise RuntimeError(f"ProPainter execution failed with code {error.returncode}: {stderr[:500]}")
    
    def set_gpu_config(self, gpu_info: Dict) -> None:
        """
        Set GPU configuration for inference.
        
        Args:
            gpu_info: Dictionary with GPU information from EnvironmentManager
        """
        self.gpu_info = gpu_info
    
    def process_chunks(self, chunks: List[Dict], width: int, height: int) -> Dict[str, Path]:
        """
        Process all chunks sequentially.
        
        Args:
            chunks: List of chunk dictionaries from SlidingWindowStrategy
            width: Target width for inference
            height: Target height for inference
            
        Returns:
            Dictionary mapping frame names to processed frame paths
        """
        import time
        results = {}
        logger.info(f"Processing {len(chunks)} chunks")
        for chunk in chunks:
            chunk_id = chunk['id']
            frames_dir = chunk['frames'][0].parent if chunk['frames'] else None
            masks_dir = chunk['masks'][0].parent if chunk['masks'] else None
            output_dir = chunk['output']
            
            if not frames_dir or not masks_dir:
                logger.warning(f"Chunk {chunk_id} missing frames or masks, skipping")
                continue
            
            logger.info(f"Processing chunk {chunk_id}: frames={frames_dir}, masks={masks_dir}, output={output_dir}")
            
            # Build and execute command
            cmd = self.build_command(frames_dir, masks_dir, output_dir, width, height)
            try:
                start_time = time.time()
                self.execute_command(cmd)
                elapsed = time.time() - start_time
                logger.info(f"Chunk {chunk_id} completed in {elapsed:.1f} seconds")
            except Exception as e:
                # Log and continue? For now, raise
                logger.error(f"Failed to process chunk {chunk_id}: {e}")
                raise RuntimeError(f"Failed to process chunk {chunk_id}: {e}")
            
            # Collect results - search recursively for PNG files
            output_frames = sorted(output_dir.rglob("*.png"))
            if not output_frames:
                # Fallback: look for any image files
                output_frames = sorted(output_dir.rglob("*.jpg")) + sorted(output_dir.rglob("*.jpeg"))
            logger.info(f"Found {len(output_frames)} output frames in {output_dir}")
            for frame_path in output_frames:
                results[frame_path.name] = frame_path
        
        logger.info(f"Total collected frames: {len(results)}")
        return results
