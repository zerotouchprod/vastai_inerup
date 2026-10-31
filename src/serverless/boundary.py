"""Chunk-boundary frame accounting for interpolation.

RIFE turns n source frames into factor*(n-1)+1 frames: it only interpolates *between* frames it has. Cut
chunk-by-chunk, the gap between a chunk's last frame and the next chunk's first frame is never interpolated,
so every chunk loses factor-1 frames (3 x 300-frame chunks at 2x gave 1797 frames instead of 1800).

Fix: the input cut is extended by a small pad (>= one source frame) so the boundary pair is interpolated with
the real next frame, and the output is then normalized to exactly round(duration * output_fps) frames: trailing
frames from the pad are dropped, and the final chunk of a video (no next frame exists) has its last frame
cloned. Upscale-only chunks are untouched.
"""

import json
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from typing import Callable, Optional

# Longer than one frame period down to 4 fps; the surplus is trimmed away again.
PAD_S = 0.25
INTERP_MODES = ("both", "interp")


def needs_boundary_fix(mode: str) -> bool:
    return mode in INTERP_MODES


def padded_duration(mode: str, duration: float) -> float:
    return duration + PAD_S if needs_boundary_fix(mode) else duration


def expected_frames(duration: float, fps: float) -> int:
    return max(1, int(round(duration * fps)))


def _probe(path: Path, run: Callable = subprocess.run) -> dict:
    r = run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=nb_read_packets,avg_frame_rate", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=60, check=True,
    )
    s = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    fps = float(Fraction(s.get("avg_frame_rate") or "0/1")) if s.get("avg_frame_rate") not in (None, "0/0") else 0.0
    return {"frames": int(s.get("nb_read_packets", 0) or 0), "fps": fps}


def normalize_frames(
    dst: Path,
    duration: float,
    lost: Optional[threading.Event] = None,
    run: Callable = subprocess.run,
    run_cmd: Optional[Callable] = None,
) -> dict:
    """Trim/pad `dst` in place to exactly round(duration * fps) video frames (audio trimmed to `duration`)."""
    info = _probe(dst, run)
    if info["fps"] <= 0:
        raise RuntimeError("cannot normalize chunk frames: output fps unknown")
    want = expected_frames(duration, info["fps"])
    report = {"frames_before": info["frames"], "frames_expected": want, "output_fps": round(info["fps"], 3)}
    if info["frames"] == want:
        report["frames_after"] = want
        return report
    short = max(0, want - info["frames"])
    tmp = dst.with_name(dst.stem + ".norm" + dst.suffix)
    vf = f"tpad=stop_mode=clone:stop={short}" if short else "null"
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(dst),
        "-vf", vf, "-frames:v", str(want),
        "-af", f"apad,atrim=0:{duration:.6f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(tmp),
    ]
    if run_cmd is not None:
        run_cmd(cmd, lost)
    else:
        run(cmd, capture_output=True, text=True, check=True, timeout=3600)
    tmp.replace(dst)
    report["frames_after"] = _probe(dst, run)["frames"]
    if report["frames_after"] != want:
        raise RuntimeError(f"chunk frame normalization failed: {report}")
    return report
