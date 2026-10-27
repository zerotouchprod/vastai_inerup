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
import threading
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional
import logging
import os

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
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total",
                    "--format=csv,nounits,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
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


# Process-wide upscalers. The worker builds a new orchestrator per chunk;
# the cache key ignores tile and batch so an OOM tile change is remembered.
_UPSCALER_CACHE = {}


class PngWriter:
    """Write PNGs on a small pool. close() waits for every write."""

    def __init__(
        self, workers: int = 2, compression: int = 1, max_pending: int = 2, timing=None
    ):
        self._compression = int(compression)
        self._semaphore = threading.Semaphore(max_pending)
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers))
        self._futures = []
        self._lock = threading.Lock()
        self._timing = timing

    def submit(self, path, image) -> None:
        owned = image.copy() if hasattr(image, "copy") else image
        self._semaphore.acquire()
        try:
            future = self._executor.submit(self._write, Path(path), owned)
        except Exception:
            self._semaphore.release()
            raise
        with self._lock:
            self._futures.append(future)

    def _write(self, path: Path, image) -> None:
        started = time.perf_counter()
        try:
            import cv2

            path.parent.mkdir(parents=True, exist_ok=True)
            ok = cv2.imwrite(
                str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, self._compression]
            )
            if not ok:
                raise RuntimeError(f"failed to write {path}")
        finally:
            if self._timing is not None:
                with self._lock:
                    self._timing["encode_s"] = self._timing.get("encode_s", 0.0) + (
                        time.perf_counter() - started
                    )
            self._semaphore.release()

    def close(self) -> None:
        error = None
        try:
            with self._lock:
                futures = list(self._futures)
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    if error is None:
                        error = exc
        finally:
            self._executor.shutdown(wait=True)
        if error is not None:
            raise error


def _is_cuda_oom(exc: BaseException) -> bool:
    if not TORCH_AVAILABLE or torch is None:
        return False
    oom = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
    return isinstance(oom, type) and isinstance(exc, oom)


def batch_forward(upsampler, frames_bgr, scale, timing=None):
    """Run one tiled-off forward.

    BGR uint8 frames become an RGB float32 NCHW batch in 0..1. When
    ``upsampler.half`` is set, the batch is cast with ``.half()`` and moved
    to ``upsampler.device``. H and W are reflect-padded up to a multiple of
    ``scale``, then a single ``upsampler.model`` call runs under
    ``torch.inference_mode()``. Padding is cropped by ``pad * scale``, values
    are clamped to 0..1, and the result is returned as BGR uint8 on CPU.
    """
    import numpy as np

    if not TORCH_AVAILABLE or torch is None:
        raise ImportError("torch is required for batch_forward")

    scale = int(scale)
    phase_start = time.perf_counter()
    channels = []
    for img in frames_bgr:
        arr = np.ascontiguousarray(img)
        rgb = arr[:, :, ::-1].astype(np.float32) / 255.0
        channels.append(np.transpose(rgb, (2, 0, 1)))
    batch = torch.from_numpy(np.stack(channels, axis=0))
    device = getattr(upsampler, "device", None)
    if getattr(upsampler, "half", False):
        batch = batch.half()
        if device is not None:
            batch = batch.to(device)
    elif device is not None:
        batch = batch.to(device)

    _, _, height, width = batch.shape
    pad_h = (scale - (height % scale)) % scale
    pad_w = (scale - (width % scale)) % scale
    if pad_h or pad_w:
        batch = torch.nn.functional.pad(batch, (0, pad_w, 0, pad_h), mode="reflect")
    if timing is not None:
        timing["preprocess_s"] = timing.get("preprocess_s", 0.0) + (
            time.perf_counter() - phase_start
        )

    inference_start = time.perf_counter()
    with torch.inference_mode():
        out = upsampler.model(batch)
    if timing is not None:
        timing["inference_s"] = timing.get("inference_s", 0.0) + (
            time.perf_counter() - inference_start
        )

    if pad_h or pad_w:
        out = out[:, :, : out.shape[2] - pad_h * scale, : out.shape[3] - pad_w * scale]
    post_start = time.perf_counter()
    out = out.clamp(0, 1).float().cpu().numpy()

    results = []
    for index in range(out.shape[0]):
        rgb = np.transpose(out[index], (1, 2, 0))
        bgr = rgb[:, :, ::-1]
        results.append(np.clip(np.rint(bgr * 255.0), 0, 255).astype(np.uint8))
    if timing is not None:
        timing["postprocess_s"] = timing.get("postprocess_s", 0.0) + (
            time.perf_counter() - post_start
        )
    return results


def clear_upscaler_cache() -> None:
    """Drop process-wide upscalers. Tests call this around each case."""
    _UPSCALER_CACHE.clear()


def get_upscaler(
    scale, half, device, tile_size, batch_size, model_name=None, logger=None
):
    """Return the process-wide upscaler for this scale, precision, and device.

    ``tile_size is None`` starts a new entry at 0. A later call with None keeps
    the tile already stored on that entry, including 512 after an OOM fallback.
    An explicit tile updates the cached object and does not reload weights.
    """
    model_name = model_name or (
        "RealESRGAN_x2plus" if int(scale) == 2 else "RealESRGAN_x4plus"
    )
    key = (int(scale), bool(half), str(device), model_name)
    existing = _UPSCALER_CACHE.get(key)
    if existing is not None:
        if tile_size is not None and int(tile_size) != int(existing.tile_size):
            existing.set_tile_size(int(tile_size))
        return existing

    chosen = 0 if tile_size is None else int(tile_size)
    processor = RealESRGANNative(
        scale=int(scale),
        model_name=model_name,
        tile_size=chosen,
        half=bool(half),
        batch_size=batch_size,
        device=str(device),
        logger=logger,
    )
    _UPSCALER_CACHE[key] = processor
    processor._load_model()
    return processor


class RealESRGANNative:
    """
    Native Python implementation of Real-ESRGAN processing.

    Replaces run_realesrgan_pytorch.sh with pure Python.
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
        device: str = "cuda",
        logger: Optional[logging.Logger] = None,
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
                model_name = "RealESRGAN_x2plus"
            elif scale == 4:
                model_name = "RealESRGAN_x4plus"
            else:
                # For other scales, use x4plus and post-scale
                model_name = "RealESRGAN_x4plus"

        self.model_name = model_name
        self.tile_size = tile_size
        self.tile_pad = tile_pad
        self.pre_pad = pre_pad
        self.half = half
        self.device = device
        self.logger = logger or logging.getLogger(__name__)

        # Remember an explicit batch before None is replaced by the VRAM table.
        # That table is only the tiled-path read grouping; tile 0 uses the
        # explicit value or 1 as the GPU batch.
        self._explicit_batch_size = batch_size
        self._batch_configured_for_resolution = batch_size is not None
        if batch_size is None:
            batch_size = GPUMemoryDetector.suggest_batch_size()
            self.logger.info(f"Auto-detected batch_size: {batch_size}")

        self.batch_size = batch_size

        # Model will be loaded on first use
        self._model = None
        self._upsampler = None
        self._use_fallback_scale = False  # Flag for x4plus->x2 fallback

    def _configure_batch_for_resolution(self, height: int, width: int) -> None:
        """Keep the legacy VRAM table, but cap auto batch by input pixel area."""
        if getattr(self, "_batch_configured_for_resolution", False):
            return
        base = int(self.batch_size)
        max_pixels = int(
            os.getenv("REAL_ESRGAN_MAX_BATCH_PIXELS", str(1920 * 1080 * base))
        )
        pixels = max(1, int(height) * int(width))
        safe = max(1, max_pixels // pixels)
        configured = min(base, safe)
        max_batch = int(os.getenv("REAL_ESRGAN_MAX_BATCH_SIZE", str(base)))
        self.batch_size = max(1, min(configured, max_batch))
        self._batch_configured_for_resolution = True
        self.logger.info(
            "Resolution-aware batch selection: resolution=%sx%s base_batch=%s selected_batch=%s max_pixels=%s",
            width,
            height,
            base,
            self.batch_size,
            max_pixels,
        )

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

        # Determine model architecture based on model name
        if "x4plus" in self.model_name or "x4" in self.model_name:
            num_block = 23
            netscale = 4
        elif "x2plus" in self.model_name or "x2" in self.model_name:
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
            scale=netscale,
        )

        # Find model weights
        model_path = self._find_model_weights()
        self.model_path = str(model_path)

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
            device=self.device,
        )

        self.logger.info("Model loaded successfully")

    def _find_model_weights(self) -> Path:
        """Find model weights file."""
        # Common locations (ordered by priority)
        possible_paths = [
            # Docker container preinstalled models (highest priority)
            Path("/opt/realesrgan_models") / f"{self.model_name}.pth",
            # Docker container paths
            Path("/workspace/project/external/Real-ESRGAN/weights")
            / f"{self.model_name}.pth",
            Path(
                "/workspace/project/external/Real-ESRGAN/experiments/pretrained_models"
            )
            / f"{self.model_name}.pth",
            Path("/root/.cache/realesrgan/weights") / f"{self.model_name}.pth",
            # Relative paths (when running locally)
            Path("weights") / f"{self.model_name}.pth",
            Path("experiments/pretrained_models") / f"{self.model_name}.pth",
            Path("external/Real-ESRGAN/weights") / f"{self.model_name}.pth",
            Path("external/Real-ESRGAN/experiments/pretrained_models")
            / f"{self.model_name}.pth",
            # User home directory
            Path.home()
            / ".cache"
            / "realesrgan"
            / "weights"
            / f"{self.model_name}.pth",
        ]

        for path in possible_paths:
            if path.exists():
                self.logger.info(f"Found model weights: {path}")
                return path

        # Never silently use x4plus for a requested x2 run: it doubles the
        # model output work and hides a broken image/model contract.
        if "x2plus" in self.model_name:
            raise FileNotFoundError(
                f"Required {self.model_name} weights are missing; refusing silent x4plus fallback"
            )

        # If not found, try to download from huggingface
        self.logger.warning(f"Model weights not found locally for {self.model_name}")
        self.logger.info(f"Searched: {[str(p) for p in possible_paths]}")
        self.logger.info("Attempting to download from HuggingFace...")

        try:
            from realesrgan.utils import download_pretrained_models

            cache_dir = Path.home() / ".cache" / "realesrgan" / "weights"
            cache_dir.mkdir(parents=True, exist_ok=True)
            model_path = cache_dir / f"{self.model_name}.pth"

            # Download model
            download_pretrained_models(
                model_name=self.model_name, model_path=str(model_path)
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

    def set_tile_size(self, tile_size: int) -> None:
        """Update the tile on this object and on a live upsampler. Does not reload weights."""
        self.tile_size = tile_size
        upsampler = self._upsampler
        if upsampler is None:
            return
        upsampler.tile_size = tile_size
        if hasattr(upsampler, "tile"):
            upsampler.tile = tile_size

    def _gpu_batch_size(self) -> int:
        """GPU batch for tile 0. The VRAM table is not a GPU batch."""
        if self.tile_size != 0:
            return 1
        explicit = getattr(self, "_explicit_batch_size", None)
        if explicit is None:
            return 1
        return max(1, int(explicit))

    def _can_batch_forward(self) -> bool:
        if self.tile_size != 0 or getattr(self, "_use_fallback_scale", False):
            return False
        upsampler = self._upsampler
        net_scale = getattr(upsampler, "scale", None) if upsampler is not None else None
        if net_scale is None:
            return False
        return int(net_scale) == int(self.scale)

    def _read_group_size(self) -> int:
        if self._can_batch_forward():
            return max(1, self._gpu_batch_size())
        return max(1, int(self.batch_size))

    def _raise_if_cancelled(self, cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("upscale cancelled")

    def _enhance_frame(self, img):
        output, _ = self._upsampler.enhance(img, outscale=self.scale)
        return output

    def _upscale_loaded(self, images, timing=None):
        """Tile-0 batch. On CUDA OOM, switch this cached object to tile 512 and enhance."""
        try:
            return batch_forward(
                self._upsampler, images, int(self.scale), timing=timing
            )
        except Exception as exc:
            if not _is_cuda_oom(exc):
                raise
            self.logger.exception(
                "Real-ESRGAN CUDA OOM: model=%s scale=%s batch=%s tile=%s images=%s",
                getattr(self, "model_name", "unknown"),
                self.scale,
                len(images),
                self.tile_size,
                len(images),
            )
        # Retry outside the except block: the traceback holds the failed
        # forward's tensors, so VRAM is only released once it is gone.
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        self.set_tile_size(512)
        self.batch_size = 1
        self._explicit_batch_size = 1
        self.logger.warning(
            "OOM recovery: batch_size=%s -> 1, tile_size -> 512", len(images)
        )
        return [self._enhance_frame(img) for img in images]

    def process_frames(
        self,
        input_frames: List[Path],
        output_dir: Path,
        progress_callback: Optional[callable] = None,
        cancel_event=None,
    ) -> List[Path]:
        """Process frames with Real-ESRGAN.

        A cancel that is already set writes nothing. Progress is one call per
        emitted frame. Tile 0 uses a single model forward per same-size group.
        """
        self._raise_if_cancelled(cancel_event)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._load_model()

        try:
            import cv2
        except ImportError as e:
            raise ImportError(
                "opencv-python not found. Install: pip install opencv-python"
            ) from e

        total = len(input_frames)
        first = (
            cv2.imread(str(input_frames[0]), cv2.IMREAD_COLOR) if input_frames else None
        )
        if first is None:
            raise ValueError("Unable to read the first input frame")
        self._configure_batch_for_resolution(first.shape[0], first.shape[1])
        self.logger.info(f"Processing {total} frames with Real-ESRGAN")
        self.logger.info(
            "Real-ESRGAN runtime: model=%s requested_scale=%s network_scale=%s "
            "resolution=%sx%s fp16=%s tile=%s tile_pad=%s pre_pad=%s "
            "batch=%s weights=%s",
            getattr(self, "model_name", "unknown"),
            self.scale,
            getattr(self._upsampler, "scale", "unknown"),
            first.shape[1],
            first.shape[0],
            self.half,
            self.tile_size,
            getattr(self, "tile_pad", 10),
            getattr(self, "pre_pad", 0),
            self.batch_size,
            getattr(self, "model_path", "unknown"),
        )
        self.logger.info(f"  Scale: {self.scale}x")
        self.logger.info(f"  Tile size: {self.tile_size}")
        self.logger.info(f"  Batch size: {self.batch_size}")
        self.logger.info(f"  Half precision: {self.half}")
        if self.tile_size != 0:
            self.logger.info("  gpu_batch=1")
        else:
            self.logger.info(f"  gpu_batch={self._gpu_batch_size()}")

        if torch is not None and torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            self.logger.info(f"  GPU: {gpu_name} ({gpu_memory:.1f}GB)")

        output_frames = []
        start_time = time.time()
        timings = {
            "decode_s": 0.0,
            "preprocess_s": 0.0,
            "inference_s": 0.0,
            "postprocess_s": 0.0,
            "encode_s": 0.0,
        }
        writer = PngWriter(timing=timings)
        try:
            index = 0
            while index < total:
                self._raise_if_cancelled(cancel_event)
                group = self._read_group_size()
                images = []
                paths = []
                consumed = 0
                while consumed < group and index + consumed < total:
                    self._raise_if_cancelled(cancel_event)
                    frame_path = input_frames[index + consumed]
                    decode_start = time.perf_counter()
                    img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
                    timings["decode_s"] += time.perf_counter() - decode_start
                    consumed += 1
                    if img is None:
                        self.logger.warning(f"Failed to load frame: {frame_path}")
                        continue
                    if images and img.shape != images[0].shape:
                        consumed -= 1
                        break
                    images.append(img)
                    paths.append(output_dir / Path(frame_path).name)
                if consumed == 0:
                    break
                index += consumed
                if not images:
                    continue
                if self._can_batch_forward():
                    outputs = self._upscale_loaded(images, timing=timings)
                else:
                    inference_start = time.perf_counter()
                    outputs = [self._enhance_frame(img) for img in images]
                    timings["inference_s"] += time.perf_counter() - inference_start
                for out_img, out_path in zip(outputs, paths):
                    self._raise_if_cancelled(cancel_event)
                    writer.submit(out_path, out_img)
                    output_frames.append(out_path)
                    current = len(output_frames)
                    if progress_callback:
                        progress_callback(current, total)
                    if current <= 10 or current % 10 == 0 or current == total:
                        elapsed = time.time() - start_time
                        fps = current / elapsed if elapsed > 0 else 0
                        eta = (total - current) / fps if fps > 0 else 0
                        self.logger.info(
                            f"Processed {current}/{total} frames "
                            f"({100 * current / total:.1f}%) | "
                            f"{fps:.2f} fps | "
                            f"ETA: {eta:.0f}s"
                        )
        finally:
            writer.close()

        elapsed = time.time() - start_time
        avg_fps = total / elapsed if elapsed > 0 else 0
        self.logger.info(
            f"Completed {total} frames in {elapsed:.1f}s ({avg_fps:.2f} fps)"
        )
        self.logger.info(
            "Real-ESRGAN timings: %s", {k: round(v, 3) for k, v in timings.items()}
        )
        return output_frames

    def process_video(
        self, input_video: Path, output_video: Path, fps: Optional[float] = None
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
            assembler.assemble_video(
                output_frames,
                output_video,
                fps=fps,
                resolution=(info.width * self.scale, info.height * self.scale),
            )

            return output_video


# CLI interface (for backward compatibility with shell script)
def main():
    """CLI entry point - mimics shell script interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Real-ESRGAN PyTorch (Native Python Implementation)"
    )
    parser.add_argument("input", help="Input file (video or directory of frames)")
    parser.add_argument("output", help="Output file or directory")
    parser.add_argument(
        "scale", type=int, nargs="?", default=4, help="Scale factor (default: 4)"
    )
    parser.add_argument(
        "--batch-size", type=int, help="Batch size (auto if not specified)"
    )
    parser.add_argument("--tile-size", type=int, default=512, help="Tile size")
    parser.add_argument("--half", action="store_true", default=True, help="Use FP16")
    parser.add_argument("--no-half", dest="half", action="store_false", help="Use FP32")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s] %(message)s", datefmt="%H:%M:%S"
    )

    input_path = Path(args.input)
    output_path = Path(args.output)

    # Create processor
    processor = RealESRGANNative(
        scale=args.scale,
        tile_size=args.tile_size,
        half=args.half,
        batch_size=args.batch_size,
    )

    # Process
    if input_path.is_file():
        # Video file
        processor.process_video(input_path, output_path)
    elif input_path.is_dir():
        # Directory of frames
        frames = sorted(input_path.glob("*.png")) or sorted(input_path.glob("*.jpg"))
        output_path.mkdir(parents=True, exist_ok=True)
        processor.process_frames(frames, output_path)
    else:
        print(f"Error: Input not found: {input_path}")
        sys.exit(1)

    print(f"✅ Success: {output_path}")


if __name__ == "__main__":
    main()
