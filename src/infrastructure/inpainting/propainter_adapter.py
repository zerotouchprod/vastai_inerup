import os
import shutil
import subprocess
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
            # Apply emergency patch for torch version parsing bug
            self._patch_propainter_misc()

        # MULTI-GPU SUPPORT: Detect available GPUs
        if torch.cuda.is_available():
            self.num_gpus = torch.cuda.device_count()
            self.devices = [f"cuda:{i}" for i in range(self.num_gpus)]
            if self.num_gpus > 1:
                logger.info(f"🚀 ProPainter Multi-GPU detected: {self.num_gpus} GPUs available")
                for i in range(self.num_gpus):
                    gpu_name = torch.cuda.get_device_name(i)
                    gpu_mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
                    logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f}GB)")
            else:
                logger.info(f"ProPainter using single GPU: {torch.cuda.get_device_name(0)}")
            self.device = "cuda:0"  # Default to first GPU
        else:
            self.num_gpus = 1
            self.devices = ["cpu"]
            self.device = "cpu"
            logger.info("ProPainter using CPU (no CUDA available)")

        # Sliding Window settings for OOM protection (Exit code -9)
        # Ultra-conservative settings for high-resolution videos
        self.CHUNK_SIZE = 10    # Process 10 frames at a time (reduced from 20 due to persistent OOM)
        self.OVERLAP = 2        # Reduced overlap proportionally

    def _patch_propainter_misc(self) -> None:
        """
        Emergency patch for ProPainter's model/misc.py to fix PyTorch version parsing bug.

        Bug: misc.py uses strict regex that crashes with IndexError on non-standard torch versions.
        Fix: Replace the problematic version parsing with a safer try-except wrapper.
        """
        misc_file = self.root / "model" / "misc.py"

        if not misc_file.exists():
            logger.debug(f"ProPainter misc.py not found at {misc_file}, skipping patch")
            return

        try:
            content = misc_file.read_text(encoding='utf-8')

            # Check if already patched
            if "# PATCHED by vastai_inerup" in content:
                logger.debug("ProPainter misc.py already patched")
                return

            # Look for the problematic line
            buggy_marker = "IS_HIGH_VERSION = [int(m) for m in list(re.findall"

            if buggy_marker not in content:
                logger.debug("ProPainter misc.py doesn't contain expected bug pattern, skipping")
                return

            # Simple and robust fix: replace the entire version detection block
            # Original problematic code:
            # IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\.([0-9]+)\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\+git.*)?$",\
            #                    torch.__version__)[0])]

            # Safe replacement:
            old_code = """IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\\.([0-9]+)\\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\\+git.*)?$",\\
                       torch.__version__)[0])]"""

            new_code = """# PATCHED by vastai_inerup: fix torch version parsing for non-standard builds
try:
    IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\\.([0-9]+)\\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\\+git.*)?$",\\
                       torch.__version__)[0])]
except (IndexError, AttributeError, ValueError):
    # Fallback for non-standard torch versions (dev builds, custom compiles)
    import torch
    version_parts = torch.__version__.split('.')
    IS_HIGH_VERSION = [int(version_parts[0]) if len(version_parts) > 0 else 1,
                       int(version_parts[1].split('+')[0].split('a')[0].split('b')[0].split('rc')[0]) if len(version_parts) > 1 else 7,
                       0]"""

            if old_code in content:
                patched_content = content.replace(old_code, new_code)
                misc_file.write_text(patched_content, encoding='utf-8')
                logger.info(f"✅ Successfully patched {misc_file} to fix PyTorch version parsing bug")
            else:
                # Try alternative format (different whitespace)
                logger.warning(f"Could not find exact match for buggy code pattern in {misc_file}")
                logger.warning("Attempting line-by-line replacement...")

                lines = content.split('\n')
                patched_lines = []
                i = 0
                patched = False

                while i < len(lines):
                    line = lines[i]

                    if "IS_HIGH_VERSION = [int(m)" in line and "re.findall" in line:
                        # Found the start of the problematic block
                        logger.info(f"Found problematic line at {i}: {line[:80]}...")

                        # Add patched version
                        indent = len(line) - len(line.lstrip())
                        patched_lines.append(" " * indent + "# PATCHED by vastai_inerup: fix torch version parsing")
                        patched_lines.append(" " * indent + "try:")
                        patched_lines.append(" " * (indent + 4) + line.strip())

                        # Continue copying until we find the closing bracket and end of statement
                        i += 1
                        while i < len(lines) and (lines[i].strip().endswith('\\') or
                                                   not lines[i-1].strip().endswith(')]')):
                            patched_lines.append(" " * (indent + 4) + lines[i].strip())
                            i += 1
                            if i < len(lines) and ')]' in lines[i-1]:
                                break

                        # Add except block
                        patched_lines.append(" " * indent + "except (IndexError, AttributeError, ValueError):")
                        patched_lines.append(" " * (indent + 4) + "import torch")
                        patched_lines.append(" " * (indent + 4) + "version_parts = torch.__version__.split('.')")
                        patched_lines.append(" " * (indent + 4) + "IS_HIGH_VERSION = [int(version_parts[0]) if len(version_parts) > 0 else 1,")
                        patched_lines.append(" " * (indent + 19) + "int(version_parts[1].split('+')[0].split('a')[0].split('b')[0].split('rc')[0]) if len(version_parts) > 1 else 7,")
                        patched_lines.append(" " * (indent + 19) + "0]")
                        patched = True
                    else:
                        patched_lines.append(line)
                        i += 1

                if patched:
                    misc_file.write_text('\n'.join(patched_lines), encoding='utf-8')
                    logger.info(f"✅ Successfully patched {misc_file} (line-by-line method)")
                else:
                    logger.warning(f"Could not apply patch to {misc_file} - manual intervention may be required")

        except Exception as e:
            logger.warning(f"Failed to patch ProPainter misc.py: {e}")
            logger.warning("ProPainter may fail on non-standard PyTorch versions")

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
        
        # Multi-GPU support: check if we should parallelize
        if self.num_gpus > 1:
            logger.info(f"🚀 Using MULTI-GPU processing with {self.num_gpus} GPUs")

        import math
        chunk_base_dir = output_dir.parent / "propainter_chunks"
        if chunk_base_dir.exists(): 
            shutil.rmtree(chunk_base_dir)
        chunk_base_dir.mkdir()
        
        step = self.CHUNK_SIZE - self.OVERLAP
        num_chunks = math.ceil((total_frames - self.OVERLAP) / step)
        
        # Prepare all chunks first
        chunks_to_process = []
        for i in range(num_chunks):
            start_idx = i * step
            end_idx = min(start_idx + self.CHUNK_SIZE, total_frames)
            
            if end_idx == total_frames:
                start_idx = max(0, total_frames - self.CHUNK_SIZE)
                
            chunk_frames = all_frames[start_idx:end_idx]
            chunk_id = f"chunk_{i:03d}"
            
            c_input = chunk_base_dir / chunk_id / "frames"
            c_mask = chunk_base_dir / chunk_id / "masks"
            c_output = chunk_base_dir / chunk_id / "output"
            c_input.mkdir(parents=True)
            c_mask.mkdir(parents=True)
            c_output.mkdir(parents=True)
            
            # Copy files
            for f in chunk_frames:
                shutil.copy(f, c_input / f.name)
                mask_src_png = mask_dir / f"{f.stem}.png"
                mask_src_jpg = mask_dir / f"{f.stem}.jpg"
                
                if mask_src_png.exists():
                    shutil.copy(mask_src_png, c_mask / mask_src_png.name)
                elif mask_src_jpg.exists():
                    shutil.copy(mask_src_jpg, c_mask / mask_src_jpg.name)
                else:
                    logger.warning(f"Mask not found for {f.name}")
            
            chunks_to_process.append({
                'chunk_id': i,
                'chunk_frames': chunk_frames,
                'input_dir': c_input,
                'mask_dir': c_mask,
                'output_dir': c_output,
            })

        # Process chunks (parallel if multi-GPU)
        processed_frames_map = {}

        if self.num_gpus > 1 and num_chunks >= self.num_gpus:
            # Multi-GPU parallel processing
            from concurrent.futures import ThreadPoolExecutor, as_completed
            import threading

            progress_lock = threading.Lock()
            completed_chunks = [0]

            def process_chunk_on_gpu(chunk_info, gpu_id):
                """Process chunk on specific GPU."""
                chunk_idx = chunk_info['chunk_id']
                logger.info(f"Processing Chunk {chunk_idx+1}/{num_chunks} on GPU {gpu_id}: Frames {len(chunk_info['chunk_frames'])}")

                # Run inference with specific GPU
                self._run_inference_subprocess(
                    chunk_info['input_dir'],
                    chunk_info['mask_dir'],
                    chunk_info['output_dir'],
                    gpu_id=gpu_id
                )

                # Collect results
                results = self._collect_chunk_results(chunk_info)

                # Update progress
                with progress_lock:
                    completed_chunks[0] += 1
                    logger.info(f"Completed {completed_chunks[0]}/{num_chunks} chunks ({100*completed_chunks[0]/num_chunks:.1f}%)")

                # Clear CUDA cache for this GPU to prevent memory fragmentation
                if torch.cuda.is_available():
                    with torch.cuda.device(gpu_id):
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()
                    import gc
                    gc.collect()

                return (chunk_idx, results)

            # Submit chunks to thread pool
            with ThreadPoolExecutor(max_workers=self.num_gpus) as executor:
                futures = []
                for chunk_info in chunks_to_process:
                    gpu_id = chunk_info['chunk_id'] % self.num_gpus
                    future = executor.submit(process_chunk_on_gpu, chunk_info, gpu_id)
                    futures.append(future)

                # Collect results
                for future in as_completed(futures):
                    try:
                        chunk_idx, chunk_results = future.result()
                        processed_frames_map.update(chunk_results)
                    except Exception as e:
                        logger.error(f"Chunk processing failed: {e}")
                        raise
        else:
            # Single GPU sequential processing
            for i, chunk_info in enumerate(chunks_to_process):
                logger.info(f"Processing Chunk {i+1}/{num_chunks}: Frames {len(chunk_info['chunk_frames'])}")

                # Run inference
                self._run_inference_subprocess(
                    chunk_info['input_dir'],
                    chunk_info['mask_dir'],
                    chunk_info['output_dir']
                )

                # Collect results
                chunk_results = self._collect_chunk_results(chunk_info)
                processed_frames_map.update(chunk_results)

                # Clear CUDA cache
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    import gc
                    gc.collect()

        # 3. Финальная сборка
        logger.info(f"Merging chunks (Found {len(processed_frames_map)} unique frames)...")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get original dimensions from first input frame
        first_input_frame = all_frames[0]
        import cv2
        first_img = cv2.imread(str(first_input_frame))
        if first_img is not None:
            orig_height, orig_width = first_img.shape[:2]
        else:
            orig_width, orig_height = 1920, 1080  # Fallback

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

        # ASPECT RATIO VALIDATION: Check and restore if needed
        output_frames = sorted(list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg")))
        if output_frames:
            self._validate_and_restore_aspect_ratio(output_frames, orig_width, orig_height)

        return output_dir

    def _run_inference_subprocess(self, video_path: Path, mask_path: Path, output_path: Path, gpu_id: int = None) -> Path:
        """
        Helper to run the actual CLI command.

        Args:
            video_path: Path to video or frames directory
            mask_path: Path to masks directory
            output_path: Path to output directory
            gpu_id: GPU ID to use (for multi-GPU processing). None = use default.
        """
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
        
        # 🔥 ADAPTIVE RESOLUTION SCALING based on available VRAM 🔥
        # ProPainter's memory usage scales with resolution^2 * sequence_length
        # RAFT flow estimation is the memory bottleneck

        # Determine which GPU to check
        check_gpu_id = gpu_id if gpu_id is not None else 0

        # Get available VRAM
        total_vram_gb = 0  # Initialize with default value
        max_dimension = 720  # Default conservative value

        if torch.cuda.is_available() and check_gpu_id < torch.cuda.device_count():
            gpu_props = torch.cuda.get_device_properties(check_gpu_id)
            total_vram_gb = gpu_props.total_memory / (1024**3)
            free_vram_gb = (gpu_props.total_memory - torch.cuda.memory_allocated(check_gpu_id)) / (1024**3)

            logger.info(f"GPU {check_gpu_id} VRAM: {free_vram_gb:.1f}GB free / {total_vram_gb:.1f}GB total")

            # Adaptive resolution limits based on available VRAM
            # These are ULTRA-CONSERVATIVE estimates to prevent OOM in RAFT flow estimation
            # RAFT memory usage: O(resolution^2 * num_frames), very sensitive to resolution
            if total_vram_gb >= 40:
                # A100, H100: can handle high-res but still conservative
                max_dimension = 1440
            elif total_vram_gb >= 24:
                # RTX 3090, 4090, A6000: be very conservative
                # Even 1080p can OOM with portrait videos due to RAFT
                max_dimension = 720  # Reduced from 1080 to prevent OOM
            elif total_vram_gb >= 16:
                # RTX 4080, 5070 Ti: 640p max
                max_dimension = 640
            elif total_vram_gb >= 12:
                # RTX 3080, 4070: 540p max
                max_dimension = 540
            elif total_vram_gb >= 8:
                # RTX 3060, 4060: 480p max
                max_dimension = 480
            else:
                # Low VRAM: 360p max
                max_dimension = 360

            logger.info(f"VRAM-adaptive max dimension: {max_dimension}px (based on {total_vram_gb:.1f}GB VRAM)")
        else:
            # CPU fallback or no GPU info available - already set above
            logger.info(f"CPU mode or no GPU info - using default max dimension: {max_dimension}px")

        # Calculate target dimensions while preserving aspect ratio
        # Scale down to fit within max_dimension
        if original_width >= original_height:
            # Landscape or square: width is longer side
            if original_width > max_dimension:
                target_width = max_dimension
                target_height = int(target_width / original_aspect_ratio)
            else:
                # Already within limits
                target_width = original_width
                target_height = original_height
        else:
            # Portrait: height is longer side
            if original_height > max_dimension:
                target_height = max_dimension
                target_width = int(target_height * original_aspect_ratio)
            else:
                # Already within limits
                target_width = original_width
                target_height = original_height

        # Ensure dimensions are divisible by 32 for ProPainter compatibility
        target_width = (target_width // 32) * 32
        target_height = (target_height // 32) * 32
        
        # Ensure minimum dimensions
        target_width = max(target_width, 32)
        target_height = max(target_height, 32)
        
        # Calculate scale factor for logging
        scale_factor = min(target_width / original_width, target_height / original_height)
        logger.info(f"ProPainter processing dimensions: {target_width}x{target_height} (scale: {scale_factor:.2f}x)")

        if scale_factor < 1.0:
            logger.warning(f"⚠️  Downscaling from {original_width}x{original_height} to {target_width}x{target_height} to fit in VRAM")
            logger.warning(f"   Output will be upscaled back to original resolution after inpainting")

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
        
        # Set environment for specific GPU if multi-GPU
        env = os.environ.copy()
        if gpu_id is not None:
            env['CUDA_VISIBLE_DEVICES'] = str(gpu_id)
            logger.info(f"Setting CUDA_VISIBLE_DEVICES={gpu_id} for this ProPainter process")

        # AGGRESSIVE MEMORY MANAGEMENT: Set PyTorch environment variables
        # These help prevent CUDA OOM errors by being more aggressive with memory management
        env['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:128,garbage_collection_threshold:0.6'
        env['CUDA_LAUNCH_BLOCKING'] = '1'  # Synchronous execution for better error tracking
        # Limit PyTorch memory caching
        env['PYTORCH_NO_CUDA_MEMORY_CACHING'] = '1'
        logger.info("Applied aggressive CUDA memory management settings")

        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                cwd=str(self.root),
                env=env,  # Pass environment with CUDA_VISIBLE_DEVICES
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

            # ASPECT RATIO VALIDATION: Check and restore if needed
            output_frames = sorted(list(output_path.glob("*.png")) + list(output_path.glob("*.jpg")))
            if output_frames:
                self._validate_and_restore_aspect_ratio(output_frames, original_width, original_height)

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
            stderr_msg = e.stderr[:2000] if e.stderr else 'None'
            logger.error(f"STDERR: {stderr_msg}")

            # Check for OOM error in stderr
            if e.stderr and ("out of memory" in e.stderr.lower() or "oom" in e.stderr.lower() or "cuda error" in e.stderr.lower()):
                logger.error("=" * 60)
                logger.error("🔥 OUT OF MEMORY ERROR DETECTED!")
                logger.error("=" * 60)
                logger.error(f"ProPainter ran out of GPU memory processing {target_width}x{target_height} resolution")
                logger.error(f"Current VRAM limit: {max_dimension}px (based on {total_vram_gb if 'total_vram_gb' in locals() else 'unknown'}GB)")
                logger.error("")
                logger.error("💡 Recommendations:")
                logger.error("  1. Reduce video resolution before processing")
                logger.error("  2. Process fewer frames per chunk (current: 10)")
                logger.error("  3. Use a GPU with more VRAM (40GB+ recommended for 4K)")
                logger.error("  4. Consider processing at 540p or lower resolution")
                logger.error("=" * 60)
                logger.error("  3. Use a GPU with more VRAM")
                logger.error("  4. The system will automatically retry with lower resolution")
                logger.error("=" * 60)

            # Clear CUDA cache before raising error
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                import gc
                gc.collect()

            raise RuntimeError(f"ProPainter execution failed with code {e.returncode}")

    def _collect_chunk_results(self, chunk_info: dict) -> dict:
        """
        Collect results from processed chunk.

        Args:
            chunk_info: Dict with 'chunk_frames', 'output_dir', etc.

        Returns:
            Dict mapping original frame names to result file paths
        """
        c_output = chunk_info['output_dir']
        chunk_frames = chunk_info['chunk_frames']

        results_map = {}

        # Look for both images and videos
        results = list(c_output.rglob("*.png")) + list(c_output.rglob("*.jpg")) + \
                  list(c_output.rglob("*.mp4")) + list(c_output.rglob("*.avi"))

        logger.info(f"   -> Chunk {chunk_info['chunk_id']+1} returned {len(results)} files (images + videos)")

        # Sort results
        results = sorted(results)

        # Process image files
        image_files = [r for r in results if r.suffix.lower() in ['.png', '.jpg', '.jpeg']]
        video_files = [r for r in results if r.suffix.lower() in ['.mp4', '.avi']]

        # Map image files to original frames
        for idx, res_file in enumerate(image_files):
            if idx < len(chunk_frames):
                original_frame = chunk_frames[idx]
                original_name = original_frame.stem
                results_map[original_name] = res_file
                logger.debug(f"Mapped ProPainter output {res_file.name} to original frame {original_name}")

        # Extract frames from videos (skip visualization videos)
        for video_file in video_files:
            if "masked_in" in video_file.name.lower():
                logger.info(f"   -> Skipping visualization video: {video_file.name}")
                continue

            logger.info(f"   -> Processing result video: {video_file.name}")
            try:
                extracted_frames = self._extract_frames_from_video(video_file, c_output)
                for frame_idx, frame_file in enumerate(extracted_frames):
                    if frame_idx < len(chunk_frames):
                        original_frame = chunk_frames[frame_idx]
                        original_name = original_frame.stem
                        results_map[original_name] = frame_file
                        logger.debug(f"Mapped extracted frame {frame_idx} from {video_file.name} to {original_name}")
                logger.info(f"   -> Extracted {len(extracted_frames)} frames from {video_file.name}")
            except Exception as e:
                logger.error(f"Failed to extract frames from video {video_file}: {e}")

        return results_map

    def _validate_and_restore_aspect_ratio(self, output_frames: list, original_width: int, original_height: int) -> list:
        """
        Validate output frame dimensions and restore original aspect ratio if needed.

        Args:
            output_frames: List of output frame paths
            original_width: Original frame width
            original_height: Original frame height

        Returns:
            List of validated/corrected frame paths
        """
        import cv2

        if not output_frames:
            return output_frames

        # Check first frame dimensions
        first_frame = cv2.imread(str(output_frames[0]))
        if first_frame is None:
            logger.warning(f"Could not read first output frame: {output_frames[0]}")
            return output_frames

        output_height, output_width = first_frame.shape[:2]
        original_aspect = original_width / original_height
        output_aspect = output_width / output_height

        logger.info(f"Aspect ratio check:")
        logger.info(f"  Original: {original_width}x{original_height} (ratio: {original_aspect:.3f})")
        logger.info(f"  Output:   {output_width}x{output_height} (ratio: {output_aspect:.3f})")

        # Check if dimensions are swapped (portrait became landscape or vice versa)
        aspect_diff = abs(original_aspect - output_aspect)
        swapped_aspect = output_height / output_width
        swapped_diff = abs(original_aspect - swapped_aspect)

        if swapped_diff < aspect_diff and swapped_diff < 0.1:
            # Dimensions are swapped! Need to rotate/transpose
            logger.warning(f"⚠️  Aspect ratio mismatch detected!")
            logger.warning(f"   Expected ratio: {original_aspect:.3f}, got: {output_aspect:.3f}")
            logger.warning(f"   Dimensions appear swapped. Rotating frames to restore aspect ratio...")

            corrected_count = 0
            for frame_path in output_frames:
                try:
                    frame = cv2.imread(str(frame_path))
                    if frame is None:
                        continue

                    # Rotate 90 degrees to restore portrait orientation
                    if original_height > original_width:
                        # Original was portrait, rotate clockwise
                        corrected = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
                    else:
                        # Original was landscape, rotate counter-clockwise
                        corrected = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

                    # Save corrected frame
                    cv2.imwrite(str(frame_path), corrected)
                    corrected_count += 1

                except Exception as e:
                    logger.error(f"Failed to rotate frame {frame_path}: {e}")

            logger.info(f"✅ Corrected aspect ratio for {corrected_count}/{len(output_frames)} frames")

        elif aspect_diff > 0.05:
            # Aspect ratio is different but not swapped - need to resize
            logger.warning(f"⚠️  Aspect ratio mismatch: {original_aspect:.3f} vs {output_aspect:.3f}")
            logger.info(f"   Resizing frames back to original dimensions...")

            resized_count = 0
            for frame_path in output_frames:
                try:
                    frame = cv2.imread(str(frame_path))
                    if frame is None:
                        continue

                    # Resize back to original dimensions
                    resized = cv2.resize(frame, (original_width, original_height),
                                       interpolation=cv2.INTER_LANCZOS4)

                    # Save resized frame
                    cv2.imwrite(str(frame_path), resized)
                    resized_count += 1

                except Exception as e:
                    logger.error(f"Failed to resize frame {frame_path}: {e}")

            logger.info(f"✅ Resized {resized_count}/{len(output_frames)} frames to {original_width}x{original_height}")
        else:
            # Aspect ratio is correct, but check if resolution differs
            # (ProPainter may have downscaled for VRAM management)
            if output_width != original_width or output_height != original_height:
                scale_ratio = original_width / output_width
                logger.info(f"Resolution differs: {output_width}x{output_height} -> {original_width}x{original_height} ({scale_ratio:.2f}x)")
                logger.info(f"Upscaling frames back to original resolution...")

                resized_count = 0
                for frame_path in output_frames:
                    try:
                        frame = cv2.imread(str(frame_path))
                        if frame is None:
                            continue

                        # Upscale back to original dimensions using high-quality interpolation
                        resized = cv2.resize(frame, (original_width, original_height),
                                           interpolation=cv2.INTER_LANCZOS4)

                        # Save resized frame
                        cv2.imwrite(str(frame_path), resized)
                        resized_count += 1

                    except Exception as e:
                        logger.error(f"Failed to upscale frame {frame_path}: {e}")

                logger.info(f"✅ Upscaled {resized_count}/{len(output_frames)} frames to {original_width}x{original_height}")
            else:
                logger.info(f"✅ Aspect ratio and resolution preserved correctly (diff: {aspect_diff:.4f})")

        return output_frames

    def _extract_frames_from_video(self, video_path: Path, output_dir: Path) -> list[Path]:
        """Extract frames from video file using ffmpeg."""
        import subprocess as sp  # Local import to avoid duplication

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
            result = sp.run(
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
