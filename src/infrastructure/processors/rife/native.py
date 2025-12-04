"""
Native Python implementation of RIFE interpolation processing.

Replaces run_rife_pytorch.sh with pure Python code.
Provides same functionality but with full Python debugging support.

Usage:
    from infrastructure.processors.rife.native import RIFENative

    processor = RIFENative(factor=2)
    output_frames = processor.process_frames(input_frames, output_dir)
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
import logging

# Try to import torch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


class RIFENative:
    """
    Native Python implementation of RIFE interpolation.

    Replaces run_rife_pytorch.sh with pure Python.
    """

    def __init__(
        self,
        factor: float = 2.0,
        model_path: Optional[Path] = None,
        scale: float = 1.0,
        device: str = 'cuda',
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize RIFE processor.

        Args:
            factor: Interpolation factor (2 = double frames)
            model_path: Path to RIFE model directory
            scale: Spatial scaling (default 1.0 = no scaling)
            device: Device to use
            logger: Logger instance
        """
        self.factor = factor
        self.scale = scale
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        # Find model
        if model_path is None:
            model_path = self._find_model_path()
        self.model_path = model_path

        # Model will be loaded on first use
        self._model = None

    def _find_model_path(self) -> Path:
        """
        Find RIFE model weights directory.

        Note: This is for model WEIGHTS (train_log/*.pkl), not the code.
        The code is loaded from external/RIFE.
        """
        possible_paths = [
            Path('/workspace/project/RIFEv4.26_0921'),  # Preinstalled weights
            Path('/workspace/project/external/RIFE/train_log'),  # Cloned repo weights
            Path('RIFEv4.26_0921'),  # Local dev
            Path('external/RIFE/train_log'),  # Local dev
        ]

        for path in possible_paths:
            if path.exists() and list(path.glob('*.pkl')):  # Check for .pkl files
                self.logger.info(f"Found RIFE model weights: {path}")
                return path

        raise FileNotFoundError(
            f"RIFE model weights not found. Searched: {[str(p) for p in possible_paths]}"
        )

    def _setup_model_package(self, rife_repo_path: Path):
        """
        Set up model package for RIFE imports.

        RIFE_HDv3.py needs 'from model.warplayer import warp' to work.
        We need to ensure the model/ directory is properly on the Python path.
        """
        # Add the RIFE repo root to sys.path (so "import model" works)
        rife_root = str(rife_repo_path.absolute())
        if rife_root not in sys.path:
            sys.path.insert(0, rife_root)
            self.logger.info(f"Added {rife_root} to sys.path")

        # Check if RIFE_HDv3.py was copied to root (done by remote_runner.sh)
        rife_hdv3_root = rife_repo_path / 'RIFE_HDv3.py'
        if rife_hdv3_root.exists():
            self.logger.info(f"✓ Found RIFE_HDv3.py in root: {rife_hdv3_root}")
            # Also copy warplayer.py if needed
            warplayer_root = rife_repo_path / 'warplayer.py'
            warplayer_model = rife_repo_path / 'model' / 'warplayer.py'
            if not warplayer_root.exists() and warplayer_model.exists():
                import shutil
                shutil.copy(warplayer_model, warplayer_root)
                self.logger.info(f"Copied warplayer.py to root")

        # Find model directory
        model_dir = rife_repo_path / 'model'
        if model_dir.exists():
            self.logger.info(f"Setting up model package from {model_dir}")

            # Create __init__.py in model/ if it doesn't exist (for Python package)
            init_file = model_dir / '__init__.py'
            if not init_file.exists():
                init_file.write_text("# RIFE model package\n")
                self.logger.info(f"Created {init_file}")

            # Verify model package can be imported
            try:
                # Force reload if already imported
                import importlib
                if 'model' in sys.modules:
                    importlib.reload(sys.modules['model'])
                if 'model.warplayer' in sys.modules:
                    importlib.reload(sys.modules['model.warplayer'])

                # Now try importing
                import model
                import model.warplayer
                self.logger.info("✓ model.warplayer loaded successfully")
            except ImportError as e:
                self.logger.warning(f"Could not import model.warplayer from model/: {e}")
                # Try to copy files to root as fallback
                try:
                    import shutil
                    for f in ['warplayer.py', 'IFNet_HDv3.py']:
                        src = model_dir / f
                        dst = rife_repo_path / f
                        if src.exists() and not dst.exists():
                            shutil.copy(src, dst)
                            self.logger.info(f"Copied {f} to root as fallback")
                except Exception as copy_err:
                    self.logger.warning(f"Fallback copy failed: {copy_err}")
        else:
            self.logger.warning(f"model/ directory not found in {rife_repo_path}, will try root files")

    def _load_model(self):
        """Load RIFE model (lazy loading)."""
        if self._model is not None:
            return

        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch not found. Install: pip install torch")

        self.logger.info(f"Loading RIFE model (weights from: {self.model_path})")

        # Find RIFE repository - prioritize preinstalled RIFE over cloned repo
        rife_repo_paths = [
            Path('/workspace/project/RIFEv4.26_0921'),  # Preinstalled RIFE (priority!)
            Path('RIFEv4.26_0921'),  # Local dev preinstalled
            Path('/workspace/project/external/RIFE'),  # Cloned repo
            Path('external/RIFE'),  # Local dev cloned
            Path(__file__).parent.parent.parent.parent.parent / 'external' / 'RIFE',  # From src/
        ]

        rife_repo_path = None
        for path in rife_repo_paths:
            # Check if this path has the actual RIFE code (not just empty model/__init__.py)
            if path and path.exists():
                # Check for train_log directory (contains actual RIFE implementation)
                has_train_log = (path / 'train_log').exists()
                # Or check for model/RIFE_HDv3.py or model/RIFE.py
                has_model_code = (path / 'model' / 'RIFE_HDv3.py').exists() or \
                                 (path / 'model' / 'RIFE.py').exists()

                if has_train_log or has_model_code:
                    rife_repo_path = path
                    self.logger.info(f"✓ Found RIFE repository with code: {path}")
                    break

        if not rife_repo_path:
            raise ImportError(
                f"RIFE repository with model code not found. Searched: {[str(p) for p in rife_repo_paths if p]}"
            )

        # Set up model package (needed for model.warplayer imports)
        self._setup_model_package(rife_repo_path)

        # Find RIFE_HDv3.py or model/RIFE.py
        # Priority: root (copied by remote_runner.sh) -> model/ -> train_log/
        model_class_paths = [
            (rife_repo_path / 'RIFE_HDv3.py', 'RIFE_HDv3_root', 'Model'),  # Copied to root by remote_runner.sh (PRIORITY!)
            (rife_repo_path / 'model' / 'RIFE_HDv3.py', 'RIFE_HDv3_model', 'Model'),  # v4.6 (model dir)
            (rife_repo_path / 'train_log' / 'RIFE_HDv3.py', 'RIFE_HDv3_train', 'Model'),  # v4.6+ (train_log)
            (rife_repo_path / 'model' / 'RIFE.py', 'RIFE_model', 'Model'),  # v4.x
            (rife_repo_path / 'train_log' / 'RIFE_HD.py', 'RIFE_HD', 'Model'),  # Older version
        ]

        model_class = None
        last_error = None

        for model_file, module_name, class_name in model_class_paths:
            if not model_file.exists():
                continue

            self.logger.info(f"Trying model file: {model_file}")
            try:
                # Import the module
                import importlib.util
                spec = importlib.util.spec_from_file_location(module_name, model_file)
                if spec is None or spec.loader is None:
                    self.logger.warning(f"Could not create spec for {model_file}")
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Get the Model class
                if hasattr(module, class_name):
                    model_class = getattr(module, class_name)
                    self.logger.info(f"✓ Successfully loaded {module_name}.{class_name} from {model_file}")
                    break
                else:
                    self.logger.warning(f"Module {module_name} does not have {class_name} class")

            except Exception as e:
                last_error = e
                self.logger.warning(f"Failed to load {model_file}: {e}")
                import traceback
                self.logger.debug(traceback.format_exc())
                continue

        if not model_class:
            tried_files = [str(p[0]) for p in model_class_paths if p[0].exists()]
            error_msg = f"Could not load RIFE Model class. Tried: {tried_files}"
            if last_error:
                error_msg += f"\nLast error: {last_error}"
            raise ImportError(error_msg)

        try:
            # Create model instance
            self._model = model_class()

            # Load model weights
            weights_path = self.model_path
            if not (weights_path / 'flownet.pkl').exists():
                # If model_path doesn't have pkl files directly, check parent
                if (weights_path.parent / 'flownet.pkl').exists():
                    weights_path = weights_path.parent

            self.logger.info(f"Loading model weights from {weights_path}")
            self._model.load_model(str(weights_path), -1)
            self._model.eval()
            self._model.device()

            self.logger.info("✓ RIFE model loaded successfully")

        except Exception as e:
            raise ImportError(
                f"Failed to load RIFE model. Weights from {self.model_path}: {e}"
            ) from e

    def _calculate_mids_per_pair(self) -> int:
        """Calculate how many intermediate frames per pair."""
        # factor 2 -> 1 mid, factor 4 -> 3 mids, etc.
        return max(1, int(self.factor) - 1)

    def _interpolate_pair(
        self,
        frame1: torch.Tensor,
        frame2: torch.Tensor,
        mids_count: int
    ) -> List[torch.Tensor]:
        """
        Interpolate between two frames.

        Args:
            frame1: First frame (tensor)
            frame2: Second frame (tensor)
            mids_count: Number of intermediate frames

        Returns:
            List of intermediate frames
        """
        mids = []

        with torch.no_grad():
            for i in range(mids_count):
                # Calculate timestep
                timestep = (i + 1) / (mids_count + 1)

                # Interpolate
                mid = self._model.inference(frame1, frame2, timestep)
                mids.append(mid)

        return mids

    def _load_frame_as_tensor(self, frame_path: Path) -> torch.Tensor:
        """Load image file as torch tensor."""
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            raise ImportError("opencv-python not found. Install: pip install opencv-python") from e

        img = cv2.imread(str(frame_path))
        if img is None:
            raise ValueError(f"Failed to load image: {frame_path}")

        # Convert BGR to RGB
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Convert to tensor [1, 3, H, W]
        img = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).float() / 255.0

        # Move to device
        img = img.to(self.device)

        return img

    def _save_tensor_as_frame(self, tensor: torch.Tensor, output_path: Path):
        """Save torch tensor as image file."""
        try:
            import cv2
            import numpy as np
        except ImportError as e:
            raise ImportError("opencv-python not found. Install: pip install opencv-python") from e

        # Tensor is [1, 3, H, W], convert to [H, W, 3]
        img = tensor.squeeze(0).permute(1, 2, 0).cpu().numpy()

        # Scale to 0-255
        img = (img * 255).clip(0, 255).astype(np.uint8)

        # Convert RGB to BGR
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # Save
        cv2.imwrite(str(output_path), img)

    def process_frames(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None
    ) -> List[Path]:
        """
        Interpolate frames using RIFE.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory
            progress_callback: Optional callback(current, total)

        Returns:
            List of output frame paths (interleaved: orig1, mid, orig2, mid, ...)
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Load model
        self._load_model()

        total_pairs = len(input_frames) - 1
        mids_per_pair = self._calculate_mids_per_pair()

        self.logger.info(f"Interpolating {len(input_frames)} frames")
        self.logger.info(f"  Factor: {self.factor}x")
        self.logger.info(f"  Pairs to process: {total_pairs}")
        self.logger.info(f"  Mids per pair: {mids_per_pair}")

        output_frames = []
        start_time = time.time()

        # Process pairs
        for idx in range(total_pairs):
            frame1_path = input_frames[idx]
            frame2_path = input_frames[idx + 1]

            try:
                # Load frames as tensors
                frame1 = self._load_frame_as_tensor(frame1_path)
                frame2 = self._load_frame_as_tensor(frame2_path)

                # Add original frame1 to output
                output_frames.append(frame1_path)

                # Generate intermediate frames
                mids = self._interpolate_pair(frame1, frame2, mids_per_pair)

                # Save intermediate frames
                for mid_idx, mid in enumerate(mids, 1):
                    mid_name = f"{frame1_path.stem}_mid_{mid_idx:02d}.png"
                    mid_path = output_dir / mid_name
                    self._save_tensor_as_frame(mid, mid_path)
                    output_frames.append(mid_path)

                # Progress
                if (idx + 1) % 10 == 0 or (idx + 1) == total_pairs:
                    elapsed = time.time() - start_time
                    fps = (idx + 1) / elapsed if elapsed > 0 else 0
                    eta = (total_pairs - idx - 1) / fps if fps > 0 else 0

                    self.logger.info(
                        f"Processed {idx+1}/{total_pairs} pairs "
                        f"({100*(idx+1)/total_pairs:.1f}%) | "
                        f"{fps:.2f} fps | "
                        f"ETA: {eta:.0f}s"
                    )

                    if progress_callback:
                        progress_callback(idx + 1, total_pairs)

            except Exception as e:
                self.logger.error(f"Failed to process pair {idx+1}/{total_pairs}: {e}")
                raise

        # Add last frame
        output_frames.append(input_frames[-1])

        elapsed = time.time() - start_time
        avg_fps = total_pairs / elapsed if elapsed > 0 else 0

        self.logger.info(
            f"✅ Completed {total_pairs} pairs in {elapsed:.1f}s "
            f"({avg_fps:.2f} fps)"
        )
        self.logger.info(f"Generated {len(output_frames)} total frames")

        return output_frames

    def process_video(
        self,
        input_video: Path,
        output_video: Path,
        fps: Optional[float] = None
    ) -> Path:
        """
        Interpolate entire video file.

        Args:
            input_video: Input video path
            output_video: Output video path
            fps: Output frame rate (auto-calculate if None)

        Returns:
            Output video path
        """
        from infrastructure.media import FFmpegExtractor, FFmpegAssembler

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
                fps = info.fps * self.factor

            # Interpolate
            output_frames = self.process_frames(frames, output_frames_dir)

            # Assemble video
            self.logger.info(f"Assembling video to {output_video}")
            assembler = FFmpegAssembler()
            result = assembler.assemble_video(
                output_frames,
                output_video,
                fps=fps,
                resolution=(info.width, info.height)
            )

            return output_video


# CLI interface (for backward compatibility)
def main():
    """CLI entry point - mimics shell script interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description='RIFE Interpolation (Native Python Implementation)'
    )
    parser.add_argument('input', help='Input file (video or directory of frames)')
    parser.add_argument('output', help='Output file or directory')
    parser.add_argument('factor', type=float, nargs='?', default=2.0,
                       help='Interpolation factor (default: 2.0)')
    parser.add_argument('--model-path', type=Path, help='Path to RIFE model')

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
    processor = RIFENative(
        factor=args.factor,
        model_path=args.model_path
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

