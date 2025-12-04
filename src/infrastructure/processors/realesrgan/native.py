"""
Native Python implementation of Real-ESRGAN processing.

Replaces run_realesrgan_pytorch.sh with pure Python code.
Provides same functionality but with full Python debugging support.

Usage:
    from infrastructure.processors.realesrgan.native import RealESRGANNative

    processor = RealESRGANNative(scale=2, tile_size=512)
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

        Conservative mapping (empirical):
        - <12GB => batch 1
        - 12-16GB => batch 2
        - 16-24GB => batch 4
        - 24-32GB => batch 8
        - >=32GB => batch 16
        """
        if vram_mb is None:
            memories = GPUMemoryDetector.get_gpu_memory_mb()
            if not memories:
                return 1  # Safe default
            vram_mb = min(memories)  # Use minimum (most conservative)

        vram_gb = vram_mb / 1024

        if vram_gb < 12:
            return 1
        elif vram_gb < 16:
            return 2
        elif vram_gb < 24:
            return 4
        elif vram_gb < 32:
            return 8
        else:
            return 16


class RealESRGANNative:
    """
    Native Python implementation of Real-ESRGAN processing.

    Replaces run_realesrgan_pytorch.sh with pure Python.
    """

    def __init__(
        self,
        scale: int = 2,
        model_name: str = 'RealESRGAN_x4plus',
        tile_size: int = 512,
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
            model_name: Model to use
            tile_size: Tile size for processing
            tile_pad: Padding for tiles
            pre_pad: Pre-padding
            half: Use FP16
            batch_size: Batch size (auto-detect if None)
            device: Device to use
            logger: Logger instance
        """
        self.scale = scale
        self.model_name = model_name
        self.tile_size = tile_size
        self.tile_pad = tile_pad
        self.pre_pad = pre_pad
        self.half = half
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        # Auto-detect batch size if not specified
        if batch_size is None:
            batch_size = GPUMemoryDetector.suggest_batch_size()
            self.logger.info(f"Auto-detected batch_size: {batch_size}")

        self.batch_size = batch_size

        # Model will be loaded on first use
        self._model = None
        self._upsampler = None

    def _load_model(self):
        """Load Real-ESRGAN model (lazy loading)."""
        if self._upsampler is not None:
            return

        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
        except ImportError as e:
            raise ImportError(
                "Real-ESRGAN dependencies not found. "
                "Install: pip install realesrgan basicsr"
            ) from e

        self.logger.info(f"Loading Real-ESRGAN model: {self.model_name}")

        # Determine model architecture
        if 'x4plus' in self.model_name:
            num_block = 23
            netscale = 4
        else:
            num_block = 6
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

        # Create upsampler
        use_half = self.half and (torch is not None and torch.cuda.is_available())
        self._upsampler = RealESRGANer(
            scale=netscale,
            model_path=str(model_path),
            model=model,
            tile=self.tile_size,
            tile_pad=self.tile_pad,
            pre_pad=self.pre_pad,
            half=use_half,
            device=self.device
        )

        self.logger.info(f"Model loaded successfully")

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

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory
            progress_callback: Optional callback(current, total)

        Returns:
            List of output frame paths
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load model
        self._load_model()

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

        # Log GPU info if available
        if torch is not None and torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            self.logger.info(f"  GPU: {gpu_name} ({gpu_memory:.1f}GB)")

        start_time = time.time()
        frame_start_time = start_time

        # Process frames
        for idx, frame_path in enumerate(input_frames, 1):
            try:
                # Load image
                self.logger.info(f"[{idx}/{total}] Loading frame: {frame_path.name}")
                img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                if img is None:
                    self.logger.warning(f"Failed to load frame: {frame_path}")
                    continue

                # Log image info for first frame
                if idx == 1:
                    h, w = img.shape[:2]
                    self.logger.info(f"  Input resolution: {w}x{h}")
                    self.logger.info(f"  Output resolution: {w*self.scale}x{h*self.scale}")

                # Upscale
                self.logger.info(f"[{idx}/{total}] Upscaling...")
                frame_start = time.time()
                output, _ = self._upsampler.enhance(img, outscale=self.scale)
                frame_time = time.time() - frame_start

                # Save
                output_path = output_dir / frame_path.name
                cv2.imwrite(str(output_path), output)
                output_frames.append(output_path)

                # Progress (show every frame for first 5, then every 5 frames)
                show_progress = idx <= 5 or idx % 5 == 0 or idx == total
                if show_progress:
                    elapsed = time.time() - start_time
                    fps = idx / elapsed if elapsed > 0 else 0
                    eta = (total - idx) / fps if fps > 0 else 0

                    self.logger.info(
                        f"✓ [{idx}/{total}] Complete "
                        f"({100*idx/total:.1f}%) | "
                        f"Frame time: {frame_time:.1f}s | "
                        f"Avg: {fps:.2f} fps | "
                        f"ETA: {eta:.0f}s"
                    )

                    if progress_callback:
                        progress_callback(idx, total)

            except Exception as e:
                self.logger.error(f"Failed to process frame {idx}/{total}: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                raise

        elapsed = time.time() - start_time
        avg_fps = total / elapsed if elapsed > 0 else 0

        self.logger.info(f"✅ Completed {total} frames in {elapsed:.1f}s ({avg_fps:.2f} fps)")

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
        from infrastructure.media.ffmpeg import FFmpegExtractor, FFmpegAssembler

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

