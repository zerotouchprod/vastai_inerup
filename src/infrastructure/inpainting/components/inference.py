"""
Inference runner for ProPainterAdapter.
Handles CLI command construction, subprocess execution, and error handling.
"""

import subprocess
import cv2
import numpy as np
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
        Build CLI command for ProPainter-Wire inference.
        
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
            "--subvideo_length", "80",  # Safe default for memory management
            "--mask_dilation", "4",     # Default dilation for better inpainting
            "--ref_stride", "10",       # Default reference stride
            "--neighbor_length", "10",  # Default neighbor length
            "--raft_iter", "20",        # Default RAFT iterations
        ]
        
        # Add FP16 flag if configured and not forcing FP32 fallback
        if self.config.USE_AMP and not self.config.get("FORCE_FP32", False):
            cmd.append("--fp16")
            logger.info("Using FP16 precision (AMP enabled)")
        else:
            logger.info("Using FP32 precision (AMP disabled or FORCE_FP32=True)")
        
        # Add save_masked_in flag for debugging if configured
        if self.config.get("SAVE_MASKED_PREVIEW", False):
            cmd.append("--save_masked_in")
        
        return cmd
    
    def execute_command(self, command: List[str], gpu_id: Optional[int] = None) -> subprocess.CompletedProcess:
        """
        Execute ProPainter-Wire command.
        
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
        
        # Note: AMP cannot be enabled via environment variable for ProPainter
        # It requires modifying the inference script to use torch.cuda.amp.autocast
        if self.config.USE_AMP:
            logger.debug("AMP is configured but requires ProPainter script modification")
        
        logger.info(f"Executing ProPainter-Wire command: {' '.join(command)}")
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                cwd=str(self.propainter_root),
                env=env,
                check=True
            )
            logger.info(f"ProPainter-Wire command succeeded with return code {result.returncode}")
            if result.stdout:
                # Log first few lines of stdout to see progress
                lines = result.stdout.strip().split('\n')
                for line in lines[:10]:  # log first 10 lines
                    if line.strip():
                        logger.info(f"ProPainter-Wire: {line[:200]}")
                if len(lines) > 10:
                    logger.info(f"... and {len(lines) - 10} more lines")
            if result.stderr:
                # Log stderr as warning
                lines = result.stderr.strip().split('\n')
                for line in lines[:5]:
                    if line.strip():
                        logger.warning(f"ProPainter-Wire stderr: {line[:200]}")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"ProPainter-Wire command failed with code {e.returncode}")
            if e.stdout:
                logger.debug(f"ProPainter-Wire stdout: {e.stdout[:500]}")
            if e.stderr:
                logger.error(f"ProPainter-Wire stderr: {e.stderr[:500]}")
            
            # Check for CUDA CUBLAS error - try fallback to FP32
            stderr_lower = e.stderr.lower() if e.stderr else ""
            if "cublas_status_invalid_value" in stderr_lower or "cuda error" in stderr_lower:
                logger.warning("CUDA CUBLAS error detected, attempting fallback to FP32")
                # Remove --fp16 flag if present and retry
                if "--fp16" in command:
                    new_command = [arg for arg in command if arg != "--fp16"]
                    logger.info("Retrying without --fp16 flag (FP32 fallback)")
                    try:
                        result = subprocess.run(
                            new_command,
                            capture_output=True,
                            text=True,
                            cwd=str(self.propainter_root),
                            env=env,
                            check=True
                        )
                        logger.info(f"FP32 fallback succeeded with return code {result.returncode}")
                        return result
                    except subprocess.CalledProcessError as e2:
                        self.handle_inference_error(e2)
                        raise
                else:
                    # Already FP32, cannot fallback further
                    self.handle_inference_error(e)
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
    
    def set_inpaint_config(self, inpaint_config):
        """
        Set inpainting configuration for wire optimizations.
        
        Args:
            inpaint_config: InpaintConfig instance
        """
        self.inpaint_config = inpaint_config
    
    def _preprocess_masks(self, masks_dir: Path) -> None:
        """
        Apply wire optimizations to masks: binarization and dilation.
        
        Args:
            masks_dir: Directory containing mask images
        """
        if not hasattr(self, 'inpaint_config') or not self.inpaint_config:
            return
        
        config = self.inpaint_config
        if not config.force_binary_mask and config.mask_dilation <= 0:
            return
        
        logger.info(f"Applying wire optimizations to masks in {masks_dir}")
        mask_files = sorted(masks_dir.glob("*.png"))
        for mask_file in mask_files:
            mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                continue
            
            # Binarization with threshold 127
            if config.force_binary_mask:
                mask = (mask > 127).astype(np.uint8) * 255
            
            # Dilation
            if config.mask_dilation > 0:
                kernel = np.ones((config.mask_dilation, config.mask_dilation), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            cv2.imwrite(str(mask_file), mask)
    
    def _postprocess_frames(self, frames_dir: Path, masks_dir: Path, output_dir: Path) -> None:
        """
        Apply wire optimizations to output frames: preserve background.
        
        Args:
            frames_dir: Directory with original frames
            masks_dir: Directory with processed masks (after preprocessing)
            output_dir: Directory with ProPainter output frames
        """
        if not hasattr(self, 'inpaint_config') or not self.inpaint_config:
            return
        
        config = self.inpaint_config
        if not config.preserve_background:
            return
        
        logger.info(f"Applying background preservation to frames in {output_dir}")
        
        # Get original frames, masks, and output frames
        original_frames = sorted(frames_dir.glob("*.png"))
        mask_files = sorted(masks_dir.glob("*.png"))
        output_frames = sorted(output_dir.glob("*.png"))
        
        if len(original_frames) != len(output_frames) or len(original_frames) != len(mask_files):
            logger.warning("Frame count mismatch, skipping background preservation")
            return
        
        for orig_path, mask_path, out_path in zip(original_frames, mask_files, output_frames):
            original = cv2.imread(str(orig_path))
            mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            inpainted = cv2.imread(str(out_path))
            
            if original is None or mask is None or inpainted is None:
                continue
            
            # Normalize mask to 0-1
            mask_norm = (mask > 127).astype(np.float32)
            mask_3ch = np.stack([mask_norm] * 3, axis=2)
            
            # Blend: inpainted * mask + original * (1 - mask)
            result = inpainted * mask_3ch + original * (1 - mask_3ch)
            result = result.astype(np.uint8)
            
            cv2.imwrite(str(out_path), result)
    
    def process_chunks(self, chunks: List[Dict], width: int, height: int) -> Dict[str, Path]:
        """
        Process all chunks sequentially.
        
        Args:
            chunks: List of chunk dictionaries from SlidingWindowStrategy
            width: Target width for inference
            height: Target height for inference
            
        Returns:
            Dictionary mapping original frame names to processed frame paths
        """
        import time
        import subprocess
        results = {}
        logger.info(f"Processing {len(chunks)} chunks")
        
        for chunk in chunks:
            chunk_id = chunk['id']
            frames_dir = chunk['frames'][0].parent if chunk['frames'] else None
            masks_dir = chunk['masks'][0].parent if chunk['masks'] else None
            output_dir = chunk['output']
            frame_indices = chunk.get('frame_indices', (0, 0))
            start_idx, end_idx = frame_indices
            
            if not frames_dir or not masks_dir:
                logger.warning(f"Chunk {chunk_id} missing frames or masks, skipping")
                continue
            
            logger.info(f"Processing chunk {chunk_id}: frames={frames_dir}, masks={masks_dir}, output={output_dir}, indices={start_idx}-{end_idx}")
            
            # Preprocess masks with wire optimizations
            self._preprocess_masks(masks_dir)
            
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
            
            # Postprocess frames to preserve background
            self._postprocess_frames(frames_dir, masks_dir, output_dir)
            
            # ProPainter-Wire outputs video file, extract frames from it
            # Look for video file with pattern *_result.mov
            video_files = list(output_dir.glob("*_result.mov"))
            if not video_files:
                # Fallback: any .mov file
                video_files = list(output_dir.glob("*.mov"))
            if not video_files:
                # Fallback: any video file
                video_files = list(output_dir.glob("*.mp4")) + list(output_dir.glob("*.avi"))
            
            if video_files:
                video_path = video_files[0]
                logger.info(f"Found output video: {video_path}")
                # Extract frames from video to PNG
                frames_output_dir = output_dir / "extracted_frames"
                frames_output_dir.mkdir(exist_ok=True)
                
                # Use ffmpeg to extract frames
                frame_pattern = frames_output_dir / "frame_%08d.png"
                extract_cmd = [
                    "ffmpeg", "-i", str(video_path),
                    "-vsync", "0",
                    "-q:v", "2",
                    str(frame_pattern)
                ]
                try:
                    subprocess.run(extract_cmd, check=True, capture_output=True)
                    logger.info(f"Extracted frames from {video_path} to {frames_output_dir}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"Failed to extract frames from video: {e.stderr}")
                    # Continue with fallback search for PNG files
                # Use extracted frames as output
                output_frames = sorted(frames_output_dir.glob("*.png"))
            else:
                # Fallback: search for PNG files directly (if script was modified to save frames)
                output_frames = sorted(output_dir.rglob("*.png"))
            
            if not output_frames:
                # Fallback: look for any image files
                output_frames = sorted(output_dir.rglob("*.jpg")) + sorted(output_dir.rglob("*.jpeg"))
            
            logger.info(f"Found {len(output_frames)} output frames in {output_dir}")
            
            # Map output frames to original frame names
            sorted_output_frames = sorted(output_frames)
            
            # Get original frame names from the chunk
            original_frames = sorted(chunk['frames']) if chunk['frames'] else []
            
            # If we have frame indices, we can map by position
            if start_idx < end_idx and len(sorted_output_frames) == (end_idx - start_idx):
                # Perfect match: output frames correspond exactly to chunk range
                for i, frame_path in enumerate(sorted_output_frames):
                    original_idx = start_idx + i
                    # Try to get original frame name from the chunk frames list
                    if i < len(original_frames):
                        original_name = original_frames[i].name
                    else:
                        # Fallback: generate frame name based on index
                        original_name = f"frame_{original_idx:08d}.png"
                    
                    results[original_name] = frame_path
                    logger.debug(f"Mapped {frame_path.name} -> {original_name}")
            else:
                # Fallback: use frame_path.name as key (may cause overwrites)
                logger.warning(f"Chunk {chunk_id}: Output frame count ({len(sorted_output_frames)}) doesn't match chunk size ({end_idx - start_idx}). Using fallback mapping.")
                for frame_path in sorted_output_frames:
                    results[frame_path.name] = frame_path
        
        logger.info(f"Total collected frames: {len(results)}")
        return results
