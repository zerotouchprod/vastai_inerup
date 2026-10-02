"""Frame-rate planning for interpolation jobs.

RIFE inserts an integer number of mid frames, so it can only multiply the frame rate by an
integer. To reach an arbitrary target (e.g. 24 -> 60 fps = 2.5x) we interpolate by the next
integer factor and then resample the assembled video to the target with ffmpeg.
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
