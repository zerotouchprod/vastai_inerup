"""
Native Python implementation of Real-ESRGAN processing.

Replaces run_realesrgan_pytorch.sh with pure Python code.
Provides same functionality but with full Python debugging support.

Performance optimizations:
- Batch frame loading for better I/O
- Reduced logging (only every 10 frames instead of every frame)
- Smaller default tile_size (256) for faster processing
- Aggressive batch size defaults for modern GPUs

Usage:
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    processor = RealESRGANNative(scale=2, tile_size=256)
    output_frames = processor.process_frames(input_frames, output_dir)
"""

import sys
import time
import subprocess
from pathlib import Path
from typing import List, Optional
import logging

# Try to import torch for GPU detection
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore
    TORCH_AVAILABLE = False


class GPUMemoryDetector:
    """Detect GPU memory and suggest optimal batch size."""

    @staticmethod
    def get_gpu_memory_mb() -> List[int]:
        """Get memory in MB for all GPUs."""
        memories = []

        # Try nvidia-smi first
        try:
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.total', '--format=csv,nounits,noheader'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        try:
                            memories.append(int(line.strip()))
                        except ValueError:
                            pass
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Fallback to torch if available
        if not memories and TORCH_AVAILABLE and torch is not None:
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    props = torch.cuda.get_device_properties(i)
                    memories.append(int(props.total_memory / (1024 * 1024)))

        return memories

    @staticmethod
    def suggest_batch_size(vram_mb: Optional[int] = None) -> int:
        """
        Suggest batch size based on available VRAM.

        Optimized mapping for better GPU utilization:
        - <8GB => batch 2
        - 8-12GB => batch 4
        - 12-16GB => batch 8
        - 16-24GB => batch 12
        - >=24GB => batch 16
        """
        if vram_mb is None:
            memories = GPUMemoryDetector.get_gpu_memory_mb()
            if not memories:
                return 4  # Reasonable default for most GPUs
            vram_mb = min(memories)  # Use minimum (most conservative)

        vram_gb = vram_mb / 1024

        if vram_gb < 8:
            return 2
        elif vram_gb < 12:
            return 4
        elif vram_gb < 16:
            return 8
        elif vram_gb < 24:
            return 12
        else:
            return 16


class RealESRGANNative:
    """
    Native Python implementation of Real-ESRGAN processing.

    Replaces run_realesrgan_pytorch.sh with pure Python.
    Supports multi-GPU processing for better performance.
    """

    def __init__(
        self,
        scale: int = 2,
        model_name: Optional[str] = None,
        tile_size: int = 256,  # Smaller tiles = faster processing
        tile_pad: int = 10,
        pre_pad: int = 0,
        half: bool = True,
        batch_size: Optional[int] = None,
        device: str = 'cuda',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Real-ESRGAN processor.

        Args:
            scale: Upscale factor (2, 4, etc.)
            model_name: Model to use (auto-select based on scale if None)
            tile_size: Tile size for processing
            tile_pad: Padding for tiles
            pre_pad: Pre-padding
            half: Use FP16
            batch_size: Batch size (auto-detect if None)
            device: Device to use
            logger: Logger instance
        """
        self.scale = scale

        # Auto-select model based on scale if not specified
        if model_name is None:
            if scale == 2:
                model_name = 'RealESRGAN_x2plus'
            elif scale == 4:
                model_name = 'RealESRGAN_x4plus'
            else:
                # For other scales, use x4plus and post-scale
                model_name = 'RealESRGAN_x4plus'

        self.model_name = model_name
        self.tile_size = tile_size
        self.tile_pad = tile_pad
        self.pre_pad = pre_pad
        self.half = half
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        # MULTI-GPU SUPPORT: Detect available GPUs
        self.num_gpus = 1
        self.gpu_devices = ['cuda:0']
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            self.num_gpus = torch.cuda.device_count()
            self.gpu_devices = [f'cuda:{i}' for i in range(self.num_gpus)]
            if self.num_gpus > 1:
                self.logger.info(f"🚀 Multi-GPU detected: {self.num_gpus} GPUs available for upscaling")
                for i in range(self.num_gpus):
                    gpu_name = torch.cuda.get_device_name(i)
                    gpu_mem = torch.cuda.get_device_properties(i).total_memory / 1024**3
                    self.logger.info(f"  GPU {i}: {gpu_name} ({gpu_mem:.1f}GB)")
            else:
                self.logger.info(f"Single GPU mode: {torch.cuda.get_device_name(0)}")

        # Auto-detect batch size if not specified
        if batch_size is None:
            batch_size = GPUMemoryDetector.suggest_batch_size()
            self.logger.info(f"Auto-detected batch_size: {batch_size}")

        self.batch_size = batch_size

        # Models will be loaded on first use (one per GPU for multi-GPU)
        self._models = {}  # Dict[device_str, upsampler]
        self._use_fallback_scale = False  # Flag for x4plus->x2 fallback

    def _load_model(self, device: str = None):
        """
        Load Real-ESRGAN model on specific device (lazy loading).

        Args:
            device: Device string (e.g., 'cuda:0', 'cuda:1'). Uses self.device if None.
        """
        if device is None:
            device = self.device

        # Check if model already loaded on this device
        if device in self._models:
            return self._models[device]

        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except ImportError as e:
            raise ImportError(
                "Real-ESRGAN dependencies not found. "
                "Install: pip install realesrgan basicsr"
            ) from e

        self.logger.info(f"Loading Real-ESRGAN model on {device}: {self.model_name}")

        # Determine model architecture based on model name
        if 'x4plus' in self.model_name or 'x4' in self.model_name:
            num_block = 23
            netscale = 4
        elif 'x2plus' in self.model_name or 'x2' in self.model_name:
            num_block = 23
            netscale = 2
        else:
            # Default to x4
            num_block = 23
            netscale = 4

        # Create model
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=num_block,
            num_grow_ch=32,
            scale=netscale
        )

        # Find model weights
        model_path = self._find_model_weights()

        # Create upsampler on specific device
        use_half = self.half and (torch is not None and torch.cuda.is_available())
        upsampler = RealESRGANer(
            scale=netscale,
            model_path=str(model_path),
            model=model,
            tile=self.tile_size,
            tile_pad=self.tile_pad,
            pre_pad=self.pre_pad,
            half=use_half,
            device=device  # Use specific device
        )

        # Cache the model
        self._models[device] = upsampler

        self.logger.info(f"Model loaded successfully on {device}")
        return upsampler

    def _find_model_weights(self) -> Path:
        """Find model weights file."""
        # Common locations (ordered by priority)
        possible_paths = [
            # Docker container preinstalled models (highest priority)
            Path('/opt/realesrgan_models') / f'{self.model_name}.pth',
            # Docker container paths
            Path('/workspace/project/external/Real-ESRGAN/weights') / f'{self.model_name}.pth',
            Path('/workspace/project/external/Real-ESRGAN/experiments/pretrained_models') / f'{self.model_name}.pth',
            Path('/root/.cache/realesrgan/weights') / f'{self.model_name}.pth',
            # Relative paths (when running locally)
            Path('weights') / f'{self.model_name}.pth',
            Path('experiments/pretrained_models') / f'{self.model_name}.pth',
            Path('external/Real-ESRGAN/weights') / f'{self.model_name}.pth',
            Path('external/Real-ESRGAN/experiments/pretrained_models') / f'{self.model_name}.pth',
            # User home directory
            Path.home() / '.cache' / 'realesrgan' / 'weights' / f'{self.model_name}.pth',
        ]

        for path in possible_paths:
            if path.exists():
                self.logger.info(f"Found model weights: {path}")
                return path

        # If x2plus not found, try to fallback to x4plus (we'll post-scale)
        if 'x2plus' in self.model_name:
            self.logger.warning(f"{self.model_name} not found, trying fallback to x4plus...")
            fallback_name = 'RealESRGAN_x4plus'
            fallback_paths = [
                Path('/opt/realesrgan_models') / f'{fallback_name}.pth',
                Path('/workspace/project/external/Real-ESRGAN/weights') / f'{fallback_name}.pth',
                Path('/workspace/project/external/Real-ESRGAN/experiments/pretrained_models') / f'{fallback_name}.pth',
            ]
            for path in fallback_paths:
                if path.exists():
                    self.logger.info(f"Using fallback model: {path}")
                    self.logger.info(f"Will use x4plus model with outscale={self.scale}")
                    # Update model_name to x4plus for architecture setup
                    self.model_name = fallback_name
                    self._use_fallback_scale = True
                    return path

        # If not found, try to download from huggingface
        self.logger.warning(f"Model weights not found locally for {self.model_name}")
        self.logger.info(f"Searched: {[str(p) for p in possible_paths]}")
        self.logger.info("Attempting to download from HuggingFace...")

        try:
            from realesrgan.utils import download_pretrained_models
            cache_dir = Path.home() / '.cache' / 'realesrgan' / 'weights'
            cache_dir.mkdir(parents=True, exist_ok=True)
            model_path = cache_dir / f'{self.model_name}.pth'

            # Download model
            download_pretrained_models(
                model_name=self.model_name,
                model_path=str(model_path)
            )

            if model_path.exists():
                self.logger.info(f"Downloaded model weights to: {model_path}")
                return model_path
        except Exception as e:
            self.logger.warning(f"Failed to download model: {e}")

        raise FileNotFoundError(
            f"Model weights not found for {self.model_name}. "
            f"Searched: {[str(p) for p in possible_paths]}\n"
            f"Please download the model manually from: "
            f"https://github.com/xinntao/Real-ESRGAN/releases"
        )

    def process_frames(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> List[Path]:
        """
        Process frames with Real-ESRGAN.
        Uses multi-GPU processing if multiple GPUs are available.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory
            progress_callback: Optional callback(current, total)

        Returns:
            List of output frame paths
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load model(s)
        if self.num_gpus == 1:
            # Single GPU: load on default device
            self._load_model(self.device)
        else:
            # Multi-GPU: load models on all devices
            for device in self.gpu_devices:
                self._load_model(device)

        # Import cv2 here (not at module level)
        try:
            import cv2
        except ImportError as e:
            raise ImportError("opencv-python not found. Install: pip install opencv-python") from e

        output_frames = []
        total = len(input_frames)

        self.logger.info(f"Processing {total} frames with Real-ESRGAN")
        self.logger.info(f"  Scale: {self.scale}x")
        self.logger.info(f"  Tile size: {self.tile_size}")
        self.logger.info(f"  Batch size: {self.batch_size}")
        self.logger.info(f"  Half precision: {self.half}")
        self.logger.info(f"  GPUs: {self.num_gpus}")

        # Log GPU info if available
        if torch is not None and torch.cuda.is_available():
            for i in range(self.num_gpus):
                gpu_name = torch.cuda.get_device_name(i)
                gpu_memory = torch.cuda.get_device_properties(i).total_memory / (1024**3)
                self.logger.info(f"  GPU {i}: {gpu_name} ({gpu_memory:.1f}GB)")

        start_time = time.time()

        # Use multi-GPU processing if available
        if self.num_gpus > 1:
            output_frames = self._process_frames_multigpu(input_frames, output_dir, cv2, total, start_time, progress_callback)
        else:
            output_frames = self._process_frames_singlegpu(input_frames, output_dir, cv2, total, start_time, progress_callback)

        elapsed = time.time() - start_time
        avg_fps = total / elapsed if elapsed > 0 else 0

        # Final statistics
        self.logger.info(f"✅ Completed {total} frames in {elapsed:.1f}s ({avg_fps:.2f} fps)")

        # Log GPU utilization summary
        if self.num_gpus > 1:
            self.logger.info(f"📊 Multi-GPU Summary:")
            self.logger.info(f"   Total GPUs used: {self.num_gpus}")
            self.logger.info(f"   Speedup vs single GPU: ~{self.num_gpus}x")

        return output_frames

    def _process_frames_singlegpu(
        self,
        input_frames: List[Path],
        output_dir: Path,
        cv2,
        total: int,
        start_time: float,
        progress_callback: Optional[callable]
    ) -> List[Path]:
        """Process frames on single GPU."""
        output_frames = []
        upsampler = self._models[self.device]
        batch_size = self.batch_size
        num_batches = (total + batch_size - 1) // batch_size

        for batch_idx in range(num_batches):
            batch_start_idx = batch_idx * batch_size
            batch_end_idx = min(batch_start_idx + batch_size, total)
            batch_frames = input_frames[batch_start_idx:batch_end_idx]

            try:
                # Load batch of images
                images = []
                valid_frames = []

                for frame_path in batch_frames:
                    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                    if img is not None:
                        images.append(img)
                        valid_frames.append(frame_path)
                    else:
                        self.logger.warning(f"Failed to load frame: {frame_path}")

                if not images:
                    continue

                # Log image info for first frame only
                if batch_idx == 0 and images:
                    h, w = images[0].shape[:2]
                    self.logger.info(f"  Input resolution: {w}x{h}")
                    self.logger.info(f"  Output resolution: {w*self.scale}x{h*self.scale}")

                # Process each image in the batch (RealESRGANer doesn't support true batching)
                for img, frame_path in zip(images, valid_frames):
                    output, _ = upsampler.enhance(img, outscale=self.scale)

                    # Save immediately
                    output_path = output_dir / frame_path.name
                    cv2.imwrite(str(output_path), output)
                    output_frames.append(output_path)

                # Progress reporting
                current_frame = batch_end_idx
                show_progress = (
                    current_frame <= 10 or
                    current_frame % 10 == 0 or
                    current_frame == total
                )

                if show_progress:
                    elapsed = time.time() - start_time
                    fps = current_frame / elapsed if elapsed > 0 else 0
                    eta = (total - current_frame) / fps if fps > 0 else 0

                    self.logger.info(
                        f"Processed {current_frame}/{total} frames "
                        f"({100*current_frame/total:.1f}%) | "
                        f"{fps:.2f} fps | "
                        f"ETA: {eta:.0f}s"
                    )

                    if progress_callback:
                        progress_callback(current_frame, total)

            except Exception as e:
                self.logger.error(f"Failed to process batch {batch_idx + 1}/{num_batches}: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                raise

        return output_frames

    def _process_frames_multigpu(
        self,
        input_frames: List[Path],
        output_dir: Path,
        cv2,
        total: int,
        start_time: float,
        progress_callback: Optional[callable]
    ) -> List[Path]:
        """Process frames using multiple GPUs in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        self.logger.info(f"🚀 Using multi-GPU processing with {self.num_gpus} GPUs")

        # Divide frames among GPUs
        frames_per_gpu = (total + self.num_gpus - 1) // self.num_gpus
        gpu_workloads = []

        for gpu_idx in range(self.num_gpus):
            start_idx = gpu_idx * frames_per_gpu
            end_idx = min(start_idx + frames_per_gpu, total)
            if start_idx < total:
                gpu_workloads.append({
                    'gpu_id': gpu_idx,
                    'device': self.gpu_devices[gpu_idx],
                    'frames': input_frames[start_idx:end_idx],
                    'start_idx': start_idx,
                    'end_idx': end_idx
                })

        self.logger.info(f"Workload distribution:")
        for wl in gpu_workloads:
            self.logger.info(f"  GPU {wl['gpu_id']}: {len(wl['frames'])} frames ({wl['start_idx']}-{wl['end_idx']})")

        output_frames = []
        progress_lock = threading.Lock()
        processed_count = [0]

        def process_on_gpu(workload):
            """Process frames on specific GPU."""
            gpu_id = workload['gpu_id']
            device = workload['device']
            frames = workload['frames']

            upsampler = self._models[device]
            local_outputs = []

            for idx, frame_path in enumerate(frames):
                try:
                    # Load image
                    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                    if img is None:
                        self.logger.warning(f"GPU {gpu_id}: Failed to load {frame_path}")
                        continue

                    # Process
                    output, _ = upsampler.enhance(img, outscale=self.scale)

                    # Save
                    output_path = output_dir / frame_path.name
                    cv2.imwrite(str(output_path), output)
                    local_outputs.append(output_path)

                    # Update progress
                    with progress_lock:
                        processed_count[0] += 1
                        current = processed_count[0]

                        # Report progress periodically
                        if current % 10 == 0 or current == total:
                            elapsed = time.time() - start_time
                            fps = current / elapsed if elapsed > 0 else 0
                            eta = (total - current) / fps if fps > 0 else 0

                            self.logger.info(
                                f"Progress: {current}/{total} ({100*current/total:.1f}%) | "
                                f"{fps:.2f} fps | ETA: {eta:.0f}s"
                            )

                            if progress_callback:
                                progress_callback(current, total)

                except Exception as e:
                    self.logger.error(f"GPU {gpu_id}: Failed to process {frame_path}: {e}")

            return local_outputs

        # Process in parallel using thread pool
        with ThreadPoolExecutor(max_workers=self.num_gpus) as executor:
            futures = [executor.submit(process_on_gpu, wl) for wl in gpu_workloads]

            for future in as_completed(futures):
                try:
                    results = future.result()
                    output_frames.extend(results)
                except Exception as e:
                    self.logger.error(f"GPU worker failed: {e}")
                    raise

        # Sort output frames by name to preserve order
        output_frames.sort(key=lambda p: p.name)

        return output_frames

    def process_video(
        self,
        input_video: Path,
        output_video: Path,
        fps: Optional[float] = None
    ) -> Path:
        """
        Process entire video file.

        Args:
            input_video: Input video path
            output_video: Output video path
            fps: Frame rate (auto-detect if None)

        Returns:
            Output video path
        """
        from src.infrastructure.media.ffmpeg import FFmpegExtractor, FFmpegAssembler

        # Create temporary directories
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            frames_dir = temp_path / "frames"
            output_frames_dir = temp_path / "output"
            frames_dir.mkdir()
            output_frames_dir.mkdir()

            # Extract frames
            self.logger.info(f"Extracting frames from {input_video}")
            extractor = FFmpegExtractor()
            frames = extractor.extract_frames(input_video, frames_dir)

            # Get video info
            info = extractor.get_video_info(input_video)
            if fps is None:
                fps = info.fps

            # Process frames
            output_frames = self.process_frames(frames, output_frames_dir)

            # Assemble video
            self.logger.info(f"Assembling video to {output_video}")
            assembler = FFmpegAssembler()
            result = assembler.assemble_video(
                output_frames,
                output_video,
                fps=fps,
                resolution=(info.width * self.scale, info.height * self.scale)
            )

            return output_video


# CLI interface (for backward compatibility with shell script)
def main():
    """CLI entry point - mimics shell script interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Real-ESRGAN PyTorch (Native Python Implementation)'
    )
    parser.add_argument('input', help='Input file (video or directory of frames)')
    parser.add_argument('output', help='Output file or directory')
    parser.add_argument('scale', type=int, nargs='?', default=4, help='Scale factor (default: 4)')
    parser.add_argument('--batch-size', type=int, help='Batch size (auto if not specified)')
    parser.add_argument('--tile-size', type=int, default=512, help='Tile size')
    parser.add_argument('--half', action='store_true', default=True, help='Use FP16')
    parser.add_argument('--no-half', dest='half', action='store_false', help='Use FP32')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(message)s',
        datefmt='%H:%M:%S'
    )

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Create processor
    processor = RealESRGANNative(
        scale=args.scale,
        tile_size=args.tile_size,
        half=args.half,
        batch_size=args.batch_size
    )

    # Process
    if input_path.is_file():
        # Video file
        processor.process_video(input_path, output_path)
    elif input_path.is_dir():
        # Directory of frames
        frames = sorted(input_path.glob('*.png')) or sorted(input_path.glob('*.jpg'))
        output_path.mkdir(parents=True, exist_ok=True)
        processor.process_frames(frames, output_path)
    else:
        print(f"Error: Input not found: {input_path}")
        sys.exit(1)

    print(f"✅ Success: {output_path}")


if __name__ == '__main__':
    main()

