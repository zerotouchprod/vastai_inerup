"""Frame-rate planning for interpolation jobs.

RIFE inserts an integer number of mid frames, so it can only multiply the frame rate by an
integer. To reach an arbitrary target (e.g. 24 -> 60 fps) output frames are sampled across the
full presentation interval of all source frames; the final source frame is held until that
interval ends.
"""
import math
import subprocess
from pathlib import Path


def interp_factor_for(target_fps: float, original_fps: float) -> int:
    """Smallest integer factor (>= 2) whose result is at least `target_fps`."""
    if original_fps <= 0:
        raise ValueError("original_fps must be positive")
    return max(2, math.ceil(target_fps / original_fps - 1e-6))


def needs_resample(produced_fps: float, target_fps: float, tolerance: float = 0.01) -> bool:
    return abs(produced_fps - target_fps) > tolerance


def resample_fps(src: Path, dst: Path, target_fps: float, crf: int = 16) -> Path:
    """Re-time a video-only file to `target_fps` (frames duplicated/dropped, duration kept)."""
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", f"fps={target_fps}", "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not dst.exists():
        raise RuntimeError(f"fps resample failed: {result.stderr.strip()[-300:]}")
    return dst


def is_integer_multiple(target_fps: float, original_fps: float, tolerance: float = 1e-3) -> bool:
    ratio = target_fps / original_fps
    return abs(ratio - round(ratio)) < tolerance


def plan_output_frames(n_src: int, src_fps: float, target_fps: float, eps: float = 1e-3):
    """Map every output frame at `target_fps` onto the source timeline.

    Returns a list of (source_index, fraction): fraction ~ 0 means "copy source frame
    `source_index`"; otherwise the frame must be interpolated between source_index and
    source_index + 1 at timestep=fraction. Target timestamps cover all `n_src` presentation
    intervals; after the final source PTS, the final frame is held to preserve duration.
    """
    if n_src < 1 or src_fps <= 0 or target_fps <= 0:
        raise ValueError("n_src, src_fps and target_fps must be positive")
    step = src_fps / target_fps
    # Each source frame occupies a full 1/src_fps interval. Include target timestamps
    # throughout the final interval and hold the last source frame where no right neighbour exists.
    count = max(1, int(math.ceil(n_src * target_fps / src_fps - eps)))
    plan = []
    for k in range(count):
        t = k * step
        i = int(math.floor(t + eps))
        frac = t - i
        if frac < eps:
            frac = 0.0
        elif frac > 1 - eps:
            i, frac = i + 1, 0.0
        if i >= n_src - 1:
            i, frac = n_src - 1, 0.0
        plan.append((i, frac))
    return plan
