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
        
        # Check if ProPainter is installed
        if not self.inference_script.exists():
            logger.warning(f"ProPainter inference script not found at {self.inference_script}")
            logger.warning("ProPainter may not be installed or path is incorrect")
        else:
            logger.info(f"ProPainter inference script found at {self.inference_script}")
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # Sliding Window settings for OOM protection (Exit code -9)
        self.CHUNK_SIZE = 20    # Process 20 frames at a time (reduced from 40 due to OOM)
        self.OVERLAP = 5        # Reduced overlap proportionally

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

        # Get video dimensions to preserve aspect ratio
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        original_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        original_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        original_aspect_ratio = original_width / original_height
        
        logger.info(f"Original video dimensions: {original_width}x{original_height} (aspect ratio: {original_aspect_ratio:.2f})")
        
        # Calculate target dimensions while preserving aspect ratio
        # ProPainter works best with dimensions divisible by 32
        # We'll scale the longer side to 960 while preserving aspect ratio
        if original_width >= original_height:
            # Landscape or square: width is longer side
            target_width = 960
            target_height = int(target_width / original_aspect_ratio)
        else:
            # Portrait: height is longer side
            target_height = 960
            target_width = int(target_height * original_aspect_ratio)
        
        # Ensure dimensions are divisible by 32 for ProPainter compatibility
        target_width = (target_width // 32) * 32
        target_height = (target_height // 32) * 32
        
        # Ensure minimum dimensions
        target_width = max(target_width, 32)
        target_height = max(target_height, 32)
        
        logger.info(f"ProPainter target dimensions: {target_width}x{target_height} (preserving aspect ratio)")

        cmd = [
            "python3", str(self.inference_script),
            "--video", str(video_path),
            "--mask", str(mask_dir),
            "--output", str(output_path.parent),
            "--save_format", "mp4",
            "--width", str(target_width), "--height", str(target_height)  # Preserve aspect ratio
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

        # 1. Get list of all frames
        # Ищем и png и jpg
        all_frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        total_frames = len(all_frames)
        
        if total_frames == 0:
            raise ValueError(f"No frames found in {frames_dir}")

        logger.info(f"Preparing ProPainter for {total_frames} frames...")
        
        # --- FAST PATH (Мало кадров) ---
        if total_frames <= self.CHUNK_SIZE:
            return self._run_inference_subprocess(frames_dir, mask_dir, output_dir)
            
        # --- SLOW PATH (Sliding Window) ---
        logger.info(f"Video too long ({total_frames} > {self.CHUNK_SIZE}). Using Sliding Window processing.")
        
        import math
        chunk_base_dir = output_dir.parent / "propainter_chunks"
        if chunk_base_dir.exists(): 
            shutil.rmtree(chunk_base_dir)
        chunk_base_dir.mkdir()
        
        step = self.CHUNK_SIZE - self.OVERLAP
        num_chunks = math.ceil((total_frames - self.OVERLAP) / step)
        
        processed_frames_map = {} 

        for i in range(num_chunks):
            start_idx = i * step
            end_idx = min(start_idx + self.CHUNK_SIZE, total_frames)
            
            if end_idx == total_frames:
                start_idx = max(0, total_frames - self.CHUNK_SIZE)
                
            chunk_frames = all_frames[start_idx:end_idx]
            chunk_id = f"chunk_{i:03d}"
            
            logger.info(f"Processing Chunk {i+1}/{num_chunks}: Frames {start_idx}-{end_idx} ({len(chunk_frames)})")
            
            c_input = chunk_base_dir / chunk_id / "frames"
            c_mask = chunk_base_dir / chunk_id / "masks"
            c_output = chunk_base_dir / chunk_id / "output"
            c_input.mkdir(parents=True)
            c_mask.mkdir(parents=True)
            c_output.mkdir(parents=True)
            
            # Копирование файлов
            for f in chunk_frames:
                shutil.copy(f, c_input / f.name)
                # Ищем маску (она может быть .png даже если кадр .jpg)
                mask_src_png = mask_dir / f"{f.stem}.png"
                mask_src_jpg = mask_dir / f"{f.stem}.jpg"
                
                if mask_src_png.exists():
                    shutil.copy(mask_src_png, c_mask / mask_src_png.name)
                elif mask_src_jpg.exists():
                    shutil.copy(mask_src_jpg, c_mask / mask_src_jpg.name)
                else:
                    logger.warning(f"Mask not found for {f.name}")
            
            # ЗАПУСК ИНФЕРЕНСА
            self._run_inference_subprocess(c_input, c_mask, c_output)
            
            # СБОР РЕЗУЛЬТАТОВ
            # ProPainter может создать подпапки. Ищем везде.
            # Look for both images and videos
            results = list(c_output.rglob("*.png")) + list(c_output.rglob("*.jpg")) + list(c_output.rglob("*.mp4")) + list(c_output.rglob("*.avi"))
            
            logger.info(f"   -> Chunk {i+1} returned {len(results)} files (images + videos)")

            # Sort results to ensure consistent ordering
            results = sorted(results)
            
            # Process image files first
            image_files = [r for r in results if r.suffix.lower() in ['.png', '.jpg', '.jpeg']]
            video_files = [r for r in results if r.suffix.lower() in ['.mp4', '.avi']]
            
            # Process image files
            for idx, res_file in enumerate(image_files):
                # It's an image file
                # ProPainter outputs files as 0000.png, 0001.png, etc.
                # Map these to the original frame names in this chunk
                if idx < len(chunk_frames):
                    original_frame = chunk_frames[idx]
                    original_name = original_frame.stem  # e.g., frame_000015
                    # Важно: сохраняем по оригинальному имени (frame_00001.png)
                    processed_frames_map[original_name] = res_file
                    logger.debug(f"Mapped ProPainter output {res_file.name} to original frame {original_name}")
                else:
                    # If we have more results than expected, use the stem as-is
                    frame_name = res_file.stem
                    processed_frames_map[frame_name] = res_file
                    logger.warning(f"Could not map ProPainter output {res_file.name} to original frame (idx={idx}, chunk_size={len(chunk_frames)})")
            
            # Process video files - ONLY process inpaint_out.mp4 (actual result), ignore masked_in.mp4 (visualization)
            for video_file in video_files:
                # Only process inpaint_out.mp4 files (actual inpainted output)
                # Skip masked_in.mp4 files (input with masks visualized)
                if "masked_in" in video_file.name.lower():
                    logger.info(f"   -> Skipping visualization video: {video_file.name}")
                    continue
                    
                logger.info(f"   -> Processing result video: {video_file.name}")
                try:
                    extracted_frames = self._extract_frames_from_video(video_file, c_output)
                    # Map each extracted frame to its corresponding original frame
                    for frame_idx, frame_file in enumerate(extracted_frames):
                        if frame_idx < len(chunk_frames):
                            original_frame = chunk_frames[frame_idx]
                            original_name = original_frame.stem  # e.g., frame_000015
                            processed_frames_map[original_name] = frame_file
                            logger.debug(f"Mapped extracted frame {frame_idx} from {video_file.name} to {original_name}")
                    logger.info(f"   -> Extracted {len(extracted_frames)} frames from {video_file.name}")
                except Exception as e:
                    logger.error(f"Failed to extract frames from video {video_file}: {e}")

            # Clear CUDA cache between chunks to prevent OOM
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                import gc
                gc.collect()

        # 3. Финальная сборка
        logger.info(f"Merging chunks (Found {len(processed_frames_map)} unique frames)...")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        final_count = 0
        # Сортируем по имени файла (frame_00001, frame_00002...)
        for stem in sorted(processed_frames_map.keys()):
            src = processed_frames_map[stem]
            # Определяем расширение целевое (как у источника результата)
            dst_name = f"{stem}{src.suffix}"
            shutil.copy(src, output_dir / dst_name)
            final_count += 1
            
        # Cleanup
        if chunk_base_dir.exists(): 
            shutil.rmtree(chunk_base_dir)
        
        if final_count == 0:
             logger.error("CRITICAL: No frames were merged! ProPainter failed to produce output files.")
        else:
             logger.info(f"✅ Merged {final_count} frames successfully.")
             
        return output_dir

    def _run_inference_subprocess(self, video_path: Path, mask_path: Path, output_path: Path) -> Path:
        """Helper to run the actual CLI command"""
        # Get original frame dimensions to preserve aspect ratio
        import cv2
        import numpy as np
        
        # Find first frame to get dimensions
        frames = sorted(list(video_path.glob("*.jpg")) + list(video_path.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {video_path}")
        
        first_frame = frames[0]
        img = cv2.imread(str(first_frame))
        if img is None:
            raise ValueError(f"Failed to read first frame: {first_frame}")
        
        original_height, original_width = img.shape[:2]
        original_aspect_ratio = original_width / original_height
        
        logger.info(f"Original frame dimensions: {original_width}x{original_height} (aspect ratio: {original_aspect_ratio:.2f})")
        
        # Calculate target dimensions while preserving aspect ratio
        # ProPainter works best with dimensions divisible by 32
        # We'll scale the longer side to 960 while preserving aspect ratio
        if original_width >= original_height:
            # Landscape or square: width is longer side
            target_width = 960
            target_height = int(target_width / original_aspect_ratio)
        else:
            # Portrait: height is longer side
            target_height = 960
            target_width = int(target_height * original_aspect_ratio)
        
        # Ensure dimensions are divisible by 32 for ProPainter compatibility
        target_width = (target_width // 32) * 32
        target_height = (target_height // 32) * 32
        
        # Ensure minimum dimensions
        target_width = max(target_width, 32)
        target_height = max(target_height, 32)
        
        logger.info(f"ProPainter target dimensions: {target_width}x{target_height} (preserving aspect ratio)")
        
        # Try with --save_frames to get individual frames instead of video
        cmd = [
            "python3", str(self.inference_script),
            "--video", str(video_path),
            "--mask", str(mask_path),
            "--output", str(output_path),
            "--width", str(target_width), "--height", str(target_height),
            "--save_frames"  # Try to get individual frames instead of video
        ]
        
        logger.info(f"Running ProPainter command: {' '.join(cmd)}")
        logger.info(f"Working directory: {self.root}")
        logger.info(f"Input frames dir: {video_path} (exists: {video_path.exists()})")
        logger.info(f"Mask dir: {mask_path} (exists: {mask_path.exists()})")
        logger.info(f"Output dir: {output_path} (exists: {output_path.exists()})")
        
        # List files in input and mask directories for debugging
        if video_path.exists():
            input_files = list(video_path.glob("*"))
            logger.info(f"Input directory contains {len(input_files)} files: {[f.name for f in input_files[:5]]}{'...' if len(input_files) > 5 else ''}")
        
        if mask_path.exists():
            mask_files = list(mask_path.glob("*"))
            logger.info(f"Mask directory contains {len(mask_files)} files: {[f.name for f in mask_files[:5]]}{'...' if len(mask_files) > 5 else ''}")
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=str(self.root),
                check=True
            )
            
            # Log ProPainter output for debugging - use INFO level to ensure we see it
            if result.stdout:
                logger.info(f"ProPainter stdout (first 1000 chars): {result.stdout[:1000]}")
            if result.stderr:
                logger.info(f"ProPainter stderr (first 1000 chars): {result.stderr[:1000]}")
            
            # --- FLATTENING LOGIC ---
            # Вытаскиваем все файлы из подпапок в корень output_path
            # Это решает проблему, когда ProPainter создает output/input_folder_name/result.png
            all_files = list(output_path.rglob("*"))
            
            # Look for both image files AND video files
            images = [f for f in all_files if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.jpeg']]
            videos = [f for f in all_files if f.is_file() and f.suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']]
            
            logger.info(f"Found {len(images)} images in output directory (after flattening)")
            logger.info(f"Found {len(videos)} videos in output directory (after flattening)")
            
            # Debug: list all files found
            if len(all_files) > 0:
                logger.info(f"All files found in output directory (max 20):")
                for i, f in enumerate(all_files[:20]):
                    logger.info(f"  {i+1}. {f.relative_to(output_path) if f.is_relative_to(output_path) else f} (size: {f.stat().st_size if f.exists() else 0} bytes)")
                if len(all_files) > 20:
                    logger.info(f"  ... and {len(all_files) - 20} more files")
            
            # Also check parent directory and sibling directories
            parent_dir = output_path.parent
            sibling_files = list(parent_dir.rglob("*"))
            sibling_images = [f for f in sibling_files if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.jpeg']]
            sibling_videos = [f for f in sibling_files if f.is_file() and f.suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']]
            logger.info(f"Found {len(sibling_images)} images in parent directory {parent_dir}")
            logger.info(f"Found {len(sibling_videos)} videos in parent directory {parent_dir}")
            
            # If we found videos but no images, ProPainter created a video file
            # We need to extract frames from the video
            if len(videos) > 0 and len(images) == 0:
                logger.info(f"ProPainter created video file(s) instead of images. Need to extract frames.")
                # Prefer inpaint_out.mp4 over masked_in.mp4 (inpaint_out is the actual result)
                video_file = None
                for v in videos:
                    if "inpaint_out" in v.name.lower():
                        video_file = v
                        break
                if video_file is None:
                    video_file = videos[0]  # Fallback to first video
                logger.info(f"Selected video file for extraction: {video_file}")
                # Extract frames from the video
                extracted_frames = self._extract_frames_from_video(video_file, output_path)
                logger.info(f"Extracted {len(extracted_frames)} frames from {video_file.name}")
                return output_path
            
            for img in images:
                # Если файл уже в корне - пропускаем
                if img.parent == output_path:
                    continue
                # Перемещаем в корень
                shutil.move(str(img), str(output_path / img.name))
                logger.info(f"Moved {img} to {output_path / img.name}")
                
            return output_path

        except subprocess.CalledProcessError as e:
            # If --save_frames fails, try without it (ProPainter might not support this flag)
            if "--save_frames" in cmd:
                logger.warning("ProPainter failed with --save_frames flag, trying without it...")
                # Remove --save_frames from command and try again
                cmd.remove("--save_frames")
                logger.info(f"Retrying with command: {' '.join(cmd)}")
                
                try:
                    result = subprocess.run(
                        cmd, 
                        capture_output=True, 
                        text=True, 
                        cwd=str(self.root),
                        check=True
                    )
                    
                    if result.stdout:
                        logger.info(f"ProPainter stdout (retry): {result.stdout[:1000]}")
                    if result.stderr:
                        logger.info(f"ProPainter stderr (retry): {result.stderr[:1000]}")
                    
                    # Check for output files
                    all_files = list(output_path.rglob("*"))
                    images = [f for f in all_files if f.is_file() and f.suffix.lower() in ['.png', '.jpg', '.jpeg']]
                    videos = [f for f in all_files if f.is_file() and f.suffix.lower() in ['.mp4', '.avi', '.mov', '.mkv']]
                    
                    logger.info(f"After retry: Found {len(images)} images, {len(videos)} videos")
                    
                    return output_path
                    
                except subprocess.CalledProcessError as e2:
                    logger.error(f"❌ ProPainter Subprocess Crashed on retry too!")
                    logger.error(f"Exit code: {e2.returncode}")
                    logger.error(f"STDOUT: {e2.stdout[:1000] if e2.stdout else 'None'}")
                    logger.error(f"STDERR: {e2.stderr[:1000] if e2.stderr else 'None'}")
                    raise RuntimeError(f"ProPainter execution failed with code {e2.returncode}")
            
            logger.error(f"❌ ProPainter Subprocess Crashed!")
            logger.error(f"Exit code: {e.returncode}")
            logger.error(f"STDOUT: {e.stdout[:1000] if e.stdout else 'None'}")
            logger.error(f"STDERR: {e.stderr[:1000] if e.stderr else 'None'}")
            # Пытаемся освободить память перед падением
            raise RuntimeError(f"ProPainter execution failed with code {e.returncode}")

    def _extract_frames_from_video(self, video_path: Path, output_dir: Path) -> list[Path]:
        """Extract frames from video file using ffmpeg."""
        import subprocess
        import tempfile
        
        # Create a temporary directory for extracted frames
        frames_dir = output_dir / "extracted_frames"
        frames_dir.mkdir(exist_ok=True)
        
        # Use ffmpeg to extract frames
        # Output pattern: frame_%04d.png
        output_pattern = str(frames_dir / "frame_%04d.png")
        
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vsync", "0",  # Don't duplicate or drop frames
            output_pattern
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Get all extracted frames
            frames = sorted(list(frames_dir.glob("*.png")))
            logger.info(f"Extracted {len(frames)} frames from {video_path}")
            return frames
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to extract frames from {video_path}: {e}")
            logger.error(f"ffmpeg stderr: {e.stderr[:500]}")
            raise RuntimeError(f"Failed to extract frames from video: {e}")

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
