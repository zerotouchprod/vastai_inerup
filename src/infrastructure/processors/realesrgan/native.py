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

import collections
import io
import os
import re
import sys
import threading
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional
import logging

# Must be set before CUDA initialises; an explicit env value always wins.
# expandable_segments reduces fragmentation OOMs; it does not create VRAM.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

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

_GIB = 2**30

# Peak activation bytes per OUTPUT pixel per frame (fp16) for the batch_forward
# path. Measured on Vast instance 58412911 (RTX 4080 16GB, x2plus,
# 1080x1920 -> 2160x3840, batch 8): the first forward held 11.31 GiB and asked
# for 7.91 GiB more (conv_up2: 8 x 64ch x 8.29 MP x 2 B) before OOM, i.e.
# (11.31 + 7.91) / 8 = 2.40 GiB per frame = ~311 B per output pixel. RRDBNet's
# tail (conv_up2 / conv_hr at output resolution, 64ch) dominates for both x2plus
# and x4plus, so both use the same factor until x4plus is measured.
_PEAK_BYTES_PER_OUTPUT_PIXEL_FP16 = {
    "RealESRGAN_x2plus": 311,
    "RealESRGAN_x4plus": 311,
}
_DEFAULT_PEAK_BYTES_PER_OUTPUT_PIXEL_FP16 = 311
_DEFAULT_VRAM_HEADROOM = 0.15
_DEFAULT_MAX_AUTO_BATCH = 8

# Safe (batch, tile) learned from OOMs in this process, keyed by
# (gpu_name, model_name, out_w, out_h). The worker builds a new orchestrator per
# chunk but keeps the process, so later chunks start from the learned value.
_SAFE_BATCH = {}
# Scope (job id) the learned safe batches belong to. A new job clears them so no
# execution state is carried from one job to another; chunks of the same job share it.
_SAFE_SCOPE = {"id": "-"}

# Stats of the last process_frames() call (read by the worker for telemetry).
LAST_UPSCALE_STATS = {}


def _env_float(name, default):
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return float(default)


def _env_int(name, default):
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return int(default)


def peak_bytes_per_output_pixel(model_name, half=True):
    """Per-frame peak activation bytes per output pixel (env-overridable)."""
    factor = _env_float(
        "REAL_ESRGAN_PEAK_BYTES_PER_OUT_PIXEL",
        _PEAK_BYTES_PER_OUTPUT_PIXEL_FP16.get(
            str(model_name), _DEFAULT_PEAK_BYTES_PER_OUTPUT_PIXEL_FP16
        ),
    )
    return factor if half else factor * 2


def estimate_auto_batch(
    out_height, out_width, model_name, free_bytes, half=True, headroom=None, cap=None
):
    """GPU batch for tile 0 from OUTPUT pixels and free VRAM.

    batch = floor(free * (1 - headroom) / (out_px * bytes_per_out_px)), clamped
    to [1, cap]. Returns (batch, detail). Examples for x2plus fp16 at
    2160x3840 output (~2.40 GiB/frame), headroom 0.15: 15.2 GiB free (16 GB
    card) -> 5; 23.2 GiB free (24 GB card) -> 8.
    """
    if headroom is None:
        headroom = _env_float("REAL_ESRGAN_VRAM_HEADROOM", _DEFAULT_VRAM_HEADROOM)
    headroom = min(0.9, max(0.0, float(headroom)))
    if cap is None:
        cap = _env_int("REAL_ESRGAN_MAX_BATCH_SIZE", _DEFAULT_MAX_AUTO_BATCH)
    cap = max(1, int(cap))
    per_frame = max(1, int(out_height) * int(out_width)) * peak_bytes_per_output_pixel(
        model_name, half
    )
    usable = max(0.0, float(free_bytes) * (1.0 - headroom))
    raw = int(usable // per_frame) if per_frame > 0 else 1
    batch = max(1, min(cap, raw))
    return batch, {
        "per_frame_gib": round(per_frame / _GIB, 2),
        "free_gib": round(float(free_bytes) / _GIB, 2),
        "usable_gib": round(usable / _GIB, 2),
        "headroom": headroom,
        "cap": cap,
        "raw": raw,
    }


def _free_vram_bytes():
    """Free bytes on cuda:0 incl. memory cached (reserved but unallocated) by torch."""
    if not (TORCH_AVAILABLE and torch is not None and torch.cuda.is_available()):
        return None
    try:
        free, _total = torch.cuda.mem_get_info(0)
        cached = torch.cuda.memory_reserved(0) - torch.cuda.memory_allocated(0)
        return int(free + max(0, cached))
    except Exception:  # noqa: BLE001
        return None


def _gpu_name():
    if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
        try:
            return str(torch.cuda.get_device_name(0))
        except Exception:  # noqa: BLE001
            return "cuda"
    return "cpu"


def begin_safe_batch_scope(scope_id) -> bool:
    """Enter the safe-batch scope of a job. Returns True when a different job's state was dropped."""
    scope = str(scope_id or "-")
    if scope == _SAFE_SCOPE["id"]:
        return False
    dropped = bool(_SAFE_BATCH)
    _SAFE_BATCH.clear()
    _SAFE_SCOPE["id"] = scope
    return dropped


def current_safe_batch_scope() -> str:
    return _SAFE_SCOPE["id"]


def safe_batch_key(gpu_name, model_name, out_width, out_height, half=True):
    return (
        _SAFE_SCOPE["id"],
        str(gpu_name),
        str(model_name),
        int(out_width),
        int(out_height),
        bool(half),
    )


def remember_safe_batch(key, batch, tile):
    _SAFE_BATCH[key] = {"batch": max(1, int(batch)), "tile": int(tile)}


def safe_batch_snapshot():
    """JSON-friendly copy of the learned safe settings in this process."""
    return [
        {
            "scope": k[0],
            "gpu": k[1],
            "model": k[2],
            "output_resolution": f"{k[3]}x{k[4]}",
            "half": k[5],
            "batch": v["batch"],
            "tile": v["tile"],
        }
        for k, v in _SAFE_BATCH.items()
    ]


def clear_safe_batches():
    _SAFE_BATCH.clear()
    _SAFE_SCOPE["id"] = "-"


def _select_perf_profile(gpu_name, model, scale, width, height, half, logger):
    """Measured profile for this exact (gpu, model, scale, input, fp16) or None. Never raises."""
    try:
        from src.infrastructure.processors.realesrgan.profiles import select_profile

        return select_profile(gpu_name, model, scale, width, height, half=half)
    except Exception as exc:  # noqa: BLE001 - a bad profiles file must not fail the job
        logger.warning(
            "Real-ESRGAN perf profiles unavailable (%s); using auto settings", exc
        )
        return None


class FpsMeter:
    """Cumulative FPS (incl. model warmup / OOM) vs rolling and steady-state FPS.

    cumulative: done / (now - start).
    recent: frames over the last ``window`` frames' wall time.
    steady: frames after the first emitted group (warmup, first CUDA kernels,
    any OOM retry) divided by the time since that group finished.
    """

    def __init__(self, start=None, window=30):
        self.start = time.time() if start is None else float(start)
        self.window = max(2, int(window))
        self._samples = collections.deque()
        self._first = None
        self._last = None

    def mark(self, done, now=None):
        now = time.time() if now is None else float(now)
        sample = (now, int(done))
        if self._first is None:
            self._first = sample
        self._last = sample
        self._samples.append(sample)
        while len(self._samples) > 1 and sample[1] - self._samples[1][1] >= self.window:
            self._samples.popleft()

    def cumulative(self, now=None):
        if self._last is None:
            return 0.0
        now = self._last[0] if now is None else float(now)
        elapsed = now - self.start
        return self._last[1] / elapsed if elapsed > 0 else 0.0

    def recent(self):
        if len(self._samples) < 2:
            return 0.0
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        return (d1 - d0) / (t1 - t0) if t1 > t0 else 0.0

    def steady(self):
        if self._first is None or self._last is None:
            return 0.0
        (t0, d0), (t1, d1) = self._first, self._last
        return (d1 - d0) / (t1 - t0) if t1 > t0 and d1 > d0 else 0.0


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
                    self._timing["png_encode_s"] = self._timing.get(
                        "png_encode_s", 0.0
                    ) + (time.perf_counter() - started)
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


_TILE_PRINT_RE = re.compile(r"^\s*Tile\s+(\d+)/(\d+)\s*$")


class _TilePrintFilter(io.TextIOBase):
    """stdout replacement used around RealESRGANer.enhance.

    realesrgan's tile_process() prints a bare ``\tTile N/M`` per tile. Those
    lines carry no context, so they are swallowed and counted; anything else
    is forwarded to the real stdout unchanged.
    """

    def __init__(self, target):
        self._target = target
        self._pending = ""
        self.tiles_seen = 0
        self.tiles_total = 0

    def writable(self):
        return True

    def write(self, data):
        self._pending += data
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._handle(line + "\n")
        return len(data)

    def _handle(self, line):
        m = _TILE_PRINT_RE.match(line)
        if m:
            self.tiles_seen += 1
            self.tiles_total = int(m.group(2))
            return
        self._target.write(line)

    def flush(self):
        if self._pending:
            self._handle(self._pending)
            self._pending = ""
        try:
            self._target.flush()
        except Exception:  # noqa: BLE001
            pass


def log_context() -> dict:
    """Job/chunk identifiers set by the serverless child (env), for log lines."""
    return {
        "job": os.getenv("AIVIDUP_LOG_JOB_ID") or "-",
        "chunk": os.getenv("AIVIDUP_LOG_CHUNK_ID") or "-",
    }


def image_revision() -> str:
    sha = os.getenv("GIT_SHA")
    if sha and sha != "unknown":
        return sha
    try:
        with open("/etc/aividup_revision", encoding="utf-8") as fh:
            return fh.read().strip() or "unknown"
    except OSError:
        return "unknown"


def _vram_mb():
    """(used_mb, peak_mb, total_mb) for cuda:0, or None without CUDA."""
    if not (TORCH_AVAILABLE and torch is not None and torch.cuda.is_available()):
        return None
    try:
        used = torch.cuda.memory_allocated(0) / 2**20
        peak = torch.cuda.max_memory_allocated(0) / 2**20
        total = torch.cuda.get_device_properties(0).total_memory / 2**20
        return round(used), round(peak), round(total)
    except Exception:  # noqa: BLE001
        return None


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
    if torch.cuda.is_available():
        torch.cuda.synchronize()
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
    scale,
    half,
    device,
    tile_size,
    batch_size,
    model_name=None,
    logger=None,
    settings_source=None,
):
    """Return cached model weights with fresh job-scoped execution settings."""
    model_name = model_name or (
        "RealESRGAN_x2plus" if int(scale) == 2 else "RealESRGAN_x4plus"
    )
    key = (int(scale), bool(half), str(device), model_name)
    existing = _UPSCALER_CACHE.get(key)
    if existing is not None:
        existing.configure_job(tile_size=tile_size, batch_size=batch_size)
        existing.settings_source = dict(settings_source or {})
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
    processor.settings_source = dict(settings_source or {})
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
        expected_model = {2: "RealESRGAN_x2plus", 4: "RealESRGAN_x4plus"}.get(
            int(scale)
        )
        if expected_model is not None and model_name != expected_model:
            raise ValueError(
                f"model {model_name!r} is incompatible with scale={scale}; expected {expected_model!r}"
            )
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
        self._auto_batch_size = batch_size
        self._initial_tile_size = tile_size
        self._oom_recovery_attempted = False

        # Model will be loaded on first use
        self._model = None
        self._upsampler = None
        self._use_fallback_scale = False  # Flag for x4plus->x2 fallback

    def _configure_batch_for_resolution(self, height: int, width: int) -> None:
        """Pick the tile-0 GPU batch for this input resolution.

        Explicit batch (REAL_ESRGAN_BATCH_SIZE / job) wins. Otherwise, with CUDA,
        the batch comes from OUTPUT pixels and free VRAM (estimate_auto_batch).
        Without free-VRAM info the legacy input-pixel cap is used. A safe
        (batch, tile) learned from an OOM in this process for the same
        (gpu, model, output resolution) caps the result.
        """
        if (
            getattr(self, "_batch_configured_for_resolution", False)
            and getattr(self, "_explicit_batch_size", None) is None
        ):
            return
        scale = int(getattr(self, "scale", 1) or 1)
        out_h, out_w = int(height) * scale, int(width) * scale
        model = getattr(self, "model_name", "unknown")
        explicit = getattr(self, "_explicit_batch_size", None)
        detail = {}
        half = bool(getattr(self, "actual_half", getattr(self, "half", True)))
        gpu = _gpu_name()
        profile = None
        # Profiles only replace the defaults: an explicit tile or batch (env/job) wins.
        if (
            explicit is None
            and self._source("tile") == "default"
            and int(getattr(self, "_initial_tile_size", self.tile_size) or 0) == 0
        ):
            profile = _select_perf_profile(
                gpu, model, scale, width, height, half, self.logger
            )
        self._perf_profile = profile
        if profile is not None:
            self.batch_size = max(1, int(profile.gpu_batch))
            if self.tile_size != profile.tile:
                self.set_tile_size(profile.tile)
            self.tile_reason = f"profile:{profile.id}"
            source = f"profile:{profile.id}"
            detail = {"reference_fps": profile.reference_fps}
        elif explicit is not None:
            self.batch_size = max(1, int(explicit))
            source = "explicit"
        else:
            free = _free_vram_bytes()
            if free is not None:
                self.batch_size, detail = estimate_auto_batch(
                    out_h, out_w, model, free, half=half
                )
                source = "auto_vram"
            else:
                base = int(self.batch_size)
                max_pixels = int(
                    os.getenv("REAL_ESRGAN_MAX_BATCH_PIXELS", str(1920 * 1080 * base))
                )
                pixels = max(1, int(height) * int(width))
                safe = max(1, max_pixels // pixels)
                max_batch = int(os.getenv("REAL_ESRGAN_MAX_BATCH_SIZE", str(base)))
                self.batch_size = max(1, min(base, safe, max_batch))
                detail = {"max_pixels": max_pixels}
                source = "legacy_input_pixels"
        key = safe_batch_key(gpu, model, out_w, out_h, half)
        self._safe_key = key
        learned = _SAFE_BATCH.get(key)
        if learned is not None:
            if learned["batch"] < self._gpu_batch_size_raw():
                self._oom_batch_cap = learned["batch"]
                source += "+learned"
            if learned["tile"] and (
                self.tile_size == 0 or learned["tile"] < self.tile_size
            ):
                self.set_tile_size(learned["tile"])
                self.tile_reason = "learned_oom"
                source += "+learned_tile"
        self.batch_source = source
        self._batch_configured_for_resolution = True
        self.logger.info(
            "Real-ESRGAN batch selection: input=%sx%s output=%sx%s model=%s gpu=%s "
            "profile=%s source=%s gpu_batch=%s tile=%s detail=%s learned=%s",
            width,
            height,
            out_w,
            out_h,
            model,
            gpu,
            profile.id if profile is not None else "none",
            source,
            self._gpu_batch_size(),
            self.tile_size,
            detail,
            learned,
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
        self.actual_half = use_half
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
        if hasattr(upsampler, "tile_size"):
            upsampler.tile_size = tile_size
        if hasattr(upsampler, "tile"):
            upsampler.tile = tile_size

    def configure_job(
        self, tile_size: Optional[int], batch_size: Optional[int]
    ) -> None:
        """Apply only this job's tuning without replacing cached model weights."""
        chosen_tile = 0 if tile_size is None else int(tile_size)
        self._explicit_batch_size = batch_size
        self.batch_size = (
            max(1, int(batch_size))
            if batch_size is not None
            else max(1, int(getattr(self, "_auto_batch_size", self.batch_size)))
        )
        self._initial_tile_size = chosen_tile
        self._batch_configured_for_resolution = batch_size is not None
        self.set_tile_size(chosen_tile)
        self._oom_recovery_attempted = False
        self._oom_batch_cap = None

    def _gpu_batch_size_raw(self) -> int:
        explicit = getattr(self, "_explicit_batch_size", None)
        if explicit is None:
            return max(1, int(self.batch_size))
        return max(1, int(explicit))

    def _gpu_batch_size(self) -> int:
        """GPU batch for tile 0, capped by an OOM step-down. The VRAM table is not a GPU batch."""
        if self.tile_size != 0:
            return 1
        batch = self._gpu_batch_size_raw()
        cap = getattr(self, "_oom_batch_cap", None)
        return max(1, min(batch, int(cap))) if cap else batch

    def _reset_execution_state(self) -> None:
        """Reset mutable per-job tuning while keeping model weights cached."""
        self._oom_recovery_attempted = False
        self._oom_batch_cap = None
        self._oom_events = []
        self._perf_profile = None
        explicit = getattr(self, "_explicit_batch_size", None)
        self.batch_size = explicit or getattr(self, "_auto_batch_size", self.batch_size)
        self._batch_configured_for_resolution = False
        initial_tile = getattr(self, "_initial_tile_size", self.tile_size)
        if self.tile_size != initial_tile:
            self.set_tile_size(initial_tile)
        self.oom_fallback = False
        self.tile_reason = self._source("tile")

    def _source(self, key: str) -> str:
        return (getattr(self, "settings_source", None) or {}).get(key, "default")

    def _synchronize_cuda(self) -> None:
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            torch.cuda.synchronize()

    def _recover_from_oom(self, images_count: int) -> None:
        if self._oom_recovery_attempted:
            raise RuntimeError(
                "Real-ESRGAN CUDA OOM persisted after one bounded recovery attempt"
            )
        self._oom_recovery_attempted = True
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        old_tile = self.tile_size
        old_reason = getattr(self, "tile_reason", self._source("tile"))
        old_gpu_batch = self._gpu_batch_size()
        new_tile = 512 if old_tile == 0 else max(128, old_tile // 2)
        self.set_tile_size(new_tile)
        self.batch_size = 1
        self.oom_fallback = True
        self.tile_reason = "oom"
        ctx = log_context()
        vram = _vram_mb()
        self.logger.warning(
            "WARNING Real-ESRGAN OOM FALLBACK job=%s chunk=%s: "
            "tile %s(%s) -> %s(oom), gpu_batch %s -> 1, read_group %s -> 1, "
            "batch_forward -> off, retry_count=1, vram_used/peak/total_mb=%s. "
            "Remaining frames of this chunk run tiled and slower.",
            ctx["job"],
            ctx["chunk"],
            old_tile,
            old_reason,
            new_tile,
            old_gpu_batch,
            images_count,
            "/".join(map(str, vram)) if vram else "n/a",
        )

    def _step_down_after_oom(self, attempted: int) -> None:
        """One OOM in batch_forward: halve the GPU batch, or tile 512 once batch is 1."""
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        old = max(1, min(self._gpu_batch_size(), int(attempted)))
        events = getattr(self, "_oom_events", None)
        if events is None:
            events = self._oom_events = []
        key = getattr(self, "_safe_key", None)
        if old > 1:
            new = max(1, old // 2)
            self._oom_batch_cap = new
            self.oom_fallback = True
            events.append({"from_batch": old, "to_batch": new, "tile": 0})
            if key is not None:
                remember_safe_batch(key, new, 0)
            ctx = log_context()
            vram = _vram_mb()
            self.logger.warning(
                "WARNING Real-ESRGAN OOM STEP-DOWN job=%s chunk=%s: gpu_batch %s -> %s, "
                "tile stays 0, retrying the same frames, oom_events=%s, vram_used/peak/total_mb=%s",
                ctx["job"],
                ctx["chunk"],
                old,
                new,
                len(events),
                "/".join(map(str, vram)) if vram else "n/a",
            )
            return
        self._recover_from_oom(attempted)
        events.append({"from_batch": 1, "to_batch": 1, "tile": self.tile_size})
        if key is not None:
            remember_safe_batch(key, 1, self.tile_size)

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

    def _enhance_frame(self, img, frame_idx=None):
        flt = _TilePrintFilter(sys.stdout)
        old = sys.stdout
        sys.stdout = flt
        try:
            output, _ = self._upsampler.enhance(img, outscale=self.scale)
        finally:
            sys.stdout = old
            flt.flush()
        if flt.tiles_seen:
            ctx = log_context()
            self.logger.info(
                "Real-ESRGAN tiled frame job=%s chunk=%s frame=%s tiles=%s/%s "
                "tile=%s tile_reason=%s oom_fallback=%s",
                ctx["job"],
                ctx["chunk"],
                frame_idx if frame_idx is not None else "?",
                flt.tiles_seen,
                flt.tiles_total,
                self.tile_size,
                getattr(self, "tile_reason", "default"),
                getattr(self, "oom_fallback", False),
            )
        return output

    def _log_startup(self, width, height, total) -> None:
        ctx = log_context()
        src = getattr(self, "settings_source", None) or {}
        gpu = "none"
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(0)
                gpu = f"{torch.cuda.get_device_name(0)} ({props.total_memory / 2**30:.1f}GB)"
            except Exception:  # noqa: BLE001
                gpu = "cuda (unknown)"
        self.logger.info(
            "Real-ESRGAN START job=%s chunk=%s frames=%s resolution=%sx%s "
            "model=%s weights=%s net_scale=%s outscale=%s x4_fallback=%s "
            "fp16=%s(%s) tile=%s(%s) tile_pad=%s gpu_batch=%s(%s) read_group=%s "
            "batch_forward=%s model_source=%s gpu=%s image_sha=%s",
            ctx["job"],
            ctx["chunk"],
            total,
            width,
            height,
            getattr(self, "model_name", "unknown"),
            getattr(self, "model_path", "unknown"),
            getattr(self._upsampler, "scale", "unknown"),
            self.scale,
            getattr(self, "_use_fallback_scale", False),
            getattr(self, "actual_half", self.half),
            src.get("half", "default"),
            self.tile_size,
            getattr(self, "tile_reason", src.get("tile", "default")),
            getattr(self, "tile_pad", 10),
            self._gpu_batch_size(),
            src.get("batch", "default"),
            self._read_group_size(),
            self._can_batch_forward(),
            src.get("model", "default"),
            gpu,
            image_revision(),
        )

    def _log_progress(self, first, last, current, total, start_time) -> None:
        ctx = log_context()
        meter = getattr(self, "_fps_meter", None)
        if meter is not None:
            fps = meter.cumulative()
            recent = meter.recent()
        else:
            elapsed = time.time() - start_time
            fps = current / elapsed if elapsed > 0 else 0
            recent = 0.0
        rate = recent or fps
        eta = (total - current) / rate if rate > 0 else 0
        vram = _vram_mb()
        self.logger.info(
            "Real-ESRGAN progress job=%s chunk=%s frames=%s-%s done=%s/%s (%.1f%%) "
            "model=%s fp16=%s tile=%s tile_reason=%s gpu_batch=%s fps_recent=%.2f "
            "fps_cum=%.2f eta=%.0fs vram_used/peak_mb=%s oom_fallback=%s",
            ctx["job"],
            ctx["chunk"],
            first,
            last,
            current,
            total,
            100 * current / total if total else 100.0,
            getattr(self, "model_name", "unknown"),
            getattr(self, "actual_half", self.half),
            self.tile_size,
            getattr(self, "tile_reason", "default"),
            self._gpu_batch_size(),
            recent,
            fps,
            eta,
            f"{vram[0]}/{vram[1]}" if vram else "n/a",
            getattr(self, "oom_fallback", False),
        )
        for h in list(self.logger.handlers) + list(logging.getLogger().handlers):
            try:
                h.flush()
            except Exception:  # noqa: BLE001
                pass

    def _upscale_loaded(self, images, timing=None):
        """Tile-0 forward in sub-batches with bounded OOM step-down.

        On CUDA OOM the same frames are retried with half the batch
        (8 -> 4 -> 2 -> 1, torch.cuda.empty_cache between tries); finished
        sub-batches are kept. Only after batch 1 OOMs does the rest go tiled
        (tile 512). At most REAL_ESRGAN_OOM_MAX_RETRIES (default 5) OOMs per call.
        """
        max_retries = max(1, _env_int("REAL_ESRGAN_OOM_MAX_RETRIES", 5))
        retries = 0
        base = getattr(self, "_frame_base", 0)
        outputs = []
        pos = 0
        while pos < len(images):
            if not self._can_batch_forward():
                outputs.extend(
                    self._enhance_frame(img, base + pos + i)
                    for i, img in enumerate(images[pos:])
                )
                break
            sub = images[pos : pos + self._gpu_batch_size()]
            oom = False
            try:
                outputs.extend(
                    batch_forward(self._upsampler, sub, int(self.scale), timing=timing)
                )
                pos += len(sub)
            except Exception as exc:
                if not _is_cuda_oom(exc):
                    raise
                retries += 1
                self.logger.warning(
                    "Real-ESRGAN CUDA OOM: model=%s scale=%s batch=%s tile=%s retry=%s/%s: %s",
                    getattr(self, "model_name", "unknown"),
                    self.scale,
                    len(sub),
                    self.tile_size,
                    retries,
                    max_retries,
                    str(exc).splitlines()[0] if str(exc) else type(exc).__name__,
                )
                if retries > max_retries:
                    raise RuntimeError(
                        f"Real-ESRGAN CUDA OOM persisted after {max_retries} bounded retries"
                    ) from exc
                oom = True
            if oom:
                # Outside the except block so the traceback (which pins the
                # failed forward's activations) is gone before empty_cache().
                self._step_down_after_oom(len(sub))
        return outputs

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
        self._reset_execution_state()
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
        if TORCH_AVAILABLE and torch is not None and torch.cuda.is_available():
            try:
                torch.cuda.reset_peak_memory_stats(0)
            except Exception:  # noqa: BLE001
                pass
        self._log_startup(first.shape[1], first.shape[0], total)

        output_frames = []
        start_time = time.time()
        self._fps_meter = FpsMeter(
            start_time, window=_env_int("REAL_ESRGAN_FPS_WINDOW", 30)
        )
        initial_gpu_batch = self._gpu_batch_size()
        initial_tile = self.tile_size
        timings = {
            "frame_read_s": 0.0,
            "preprocess_s": 0.0,
            "inference_s": 0.0,
            "postprocess_s": 0.0,
            "png_encode_s": 0.0,
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
                    timings["frame_read_s"] += time.perf_counter() - decode_start
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
                group_first = index
                index += consumed
                if not images:
                    continue
                self._frame_base = group_first
                if self._can_batch_forward():
                    outputs = self._upscale_loaded(images, timing=timings)
                else:
                    inference_start = time.perf_counter()
                    try:
                        outputs = [
                            self._enhance_frame(img, group_first + i)
                            for i, img in enumerate(images)
                        ]
                    except Exception as exc:
                        if not _is_cuda_oom(exc):
                            raise
                        self.logger.exception(
                            "Real-ESRGAN CUDA OOM in tiled path: model=%s scale=%s tile=%s images=%s",
                            getattr(self, "model_name", "unknown"),
                            self.scale,
                            self.tile_size,
                            len(images),
                        )
                        self._recover_from_oom(len(images))
                        outputs = [
                            self._enhance_frame(img, group_first + i)
                            for i, img in enumerate(images)
                        ]
                    self._synchronize_cuda()
                    timings["inference_s"] += time.perf_counter() - inference_start
                for out_img, out_path in zip(outputs, paths):
                    self._raise_if_cancelled(cancel_event)
                    writer.submit(out_path, out_img)
                    output_frames.append(out_path)
                    current = len(output_frames)
                    if progress_callback:
                        progress_callback(current, total)
                last_frame = group_first + consumed - 1
                done = len(output_frames)
                self._fps_meter.mark(done)
                if (
                    done <= 10
                    or done // 10 != (done - len(outputs)) // 10
                    or done == total
                ):
                    self._log_progress(group_first, last_frame, done, total, start_time)
        finally:
            writer.close()

        elapsed = time.time() - start_time
        avg_fps = total / elapsed if elapsed > 0 else 0
        steady_fps = self._fps_meter.steady()
        ctx = log_context()
        vram = _vram_mb()
        key = getattr(self, "_safe_key", None)
        profile = getattr(self, "_perf_profile", None)
        LAST_UPSCALE_STATS.clear()
        LAST_UPSCALE_STATS.update(
            {
                "gpu": key[1] if key else _gpu_name(),
                "model": getattr(self, "model_name", "unknown"),
                "output_resolution": f"{key[3]}x{key[4]}" if key else None,
                "batch_source": getattr(self, "batch_source", "unknown"),
                "profile_id": profile.id if profile is not None else None,
                "profile": profile.summary() if profile is not None else None,
                "initial_gpu_batch": initial_gpu_batch,
                "initial_tile": initial_tile,
                "final_gpu_batch": self._gpu_batch_size(),
                "final_tile": self.tile_size,
                "oom_events": list(getattr(self, "_oom_events", []) or []),
                "frames": total,
                "elapsed_s": round(elapsed, 2),
                "fps_cumulative": round(avg_fps, 3),
                "fps_steady": round(steady_fps, 3),
                "vram_peak_mb": vram[1] if vram else None,
                "vram_total_mb": vram[2] if vram else None,
                "safe_batches": safe_batch_snapshot(),
            }
        )
        self.logger.info(
            "Real-ESRGAN DONE job=%s chunk=%s frames=%s elapsed=%.1fs fps_cum=%.2f "
            "fps_steady=%.2f "
            "model=%s tile=%s tile_reason=%s gpu_batch=%s vram_peak_mb=%s oom_fallback=%s",
            ctx["job"],
            ctx["chunk"],
            total,
            elapsed,
            avg_fps,
            steady_fps,
            getattr(self, "model_name", "unknown"),
            self.tile_size,
            getattr(self, "tile_reason", "default"),
            self._gpu_batch_size(),
            vram[1] if vram else "n/a",
            getattr(self, "oom_fallback", False),
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
