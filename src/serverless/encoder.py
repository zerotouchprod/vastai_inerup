"""NVENC probe with libx264 fallback.

MIG slices and some hosts expose no NVENC engine even though ffmpeg lists h264_nvenc, so we do a real
1-second encode instead of trusting `ffmpeg -encoders`. Only the final encode moves to CPU; RIFE and
Real-ESRGAN stay on the GPU regardless.
"""

import os
import subprocess
import time
from typing import Any, Callable, Dict

NVENC = "h264_nvenc"
X264 = "libx264"
ALLOWED = (NVENC, X264)


def probe_nvenc(
    run: Callable = subprocess.run, timeout: float = 30.0
) -> Dict[str, Any]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=256x256:rate=30:duration=1",
        "-c:v",
        NVENC,
        "-pix_fmt",
        "yuv420p",
        "-f",
        "null",
        "-",
    ]
    t = time.monotonic()
    try:
        r = run(cmd, capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        err = "" if ok else (r.stderr or "")[-600:]
    except Exception as e:  # noqa: BLE001 - timeout / missing ffmpeg
        ok, err = False, f"{type(e).__name__}: {e}"[:600]
    return {
        "nvenc_ok": ok,
        "nvenc_error": err or None,
        "probe_s": round(time.monotonic() - t, 2),
    }


def select_encoder(probe: Dict[str, Any], override: str = None) -> Dict[str, Any]:
    """Encoder decision. AIVIDUP_SLS_ENCODER=libx264|h264_nvenc forces one (nvenc only if the probe passed)."""
    override = (
        override if override is not None else os.environ.get("AIVIDUP_SLS_ENCODER", "")
    ).strip()
    if override == X264:
        return {"encoder": X264, "reason": "override"}
    if probe.get("nvenc_ok"):
        return {"encoder": NVENC, "reason": "probe_ok"}
    return {"encoder": X264, "reason": "nvenc_probe_failed"}


def apply_to_assembler(encoder: str) -> None:
    """Make the shared FFmpegAssembler prefer `encoder` in this process only (prod worker code is unchanged)."""
    if encoder not in ALLOWED:
        raise ValueError(f"unsupported encoder {encoder}")
    from src.infrastructure.media import assembler as asm

    orig = (
        getattr(asm.FFmpegAssembler, "_aividup_orig_init", None)
        or asm.FFmpegAssembler.__init__
    )

    def __init__(self, *a, **kw):
        orig(self, *a, **kw)
        self._preferred_encoder = encoder

    asm.FFmpegAssembler._aividup_orig_init = orig
    asm.FFmpegAssembler.__init__ = __init__
