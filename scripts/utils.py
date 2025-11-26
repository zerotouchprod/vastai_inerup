#!/usr/bin/env python3
"""Utility helpers for video file detection.

Provides is_video_key(key, probe=False) which returns True if key looks like a video file.
- First checks case-insensitive extension whitelist: .mp4, .mkv, .mov, .avi, .webm, .mjpeg, .mpeg, .mpg
- If probe=True, will run ffprobe on a local path or URL to confirm presence of a video stream (v:0).

This helper is safe and conservative: prefers extension check (fast) and falls back to probe only when requested.
"""

import subprocess
from typing import Optional

EXT_WHITELIST = ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.mjpeg', '.mpeg', '.mpg')


def is_video_key(key: Optional[str], probe: bool = False) -> bool:
    """Return True if a key/path likely refers to a video file.

    Args:
        key: object key or filename or URL
        probe: if True and key is a local path or URL accessible, run ffprobe to verify video stream
    """
    if not key:
        return False
    key = str(key)
    # quick extension check (case-insensitive)
    lower = key.lower()
    for ext in EXT_WHITELIST:
        if lower.endswith(ext):
            return True

    if not probe:
        return False

    # If probe requested, attempt to run ffprobe. Works for local files and many URLs.
    # Be conservative: any failure -> False.
    try:
        cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=index', '-of', 'default=noprint_wrappers=1:nokey=1', key]
        # On Windows, subprocess.run handles list form fine.
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        if res.returncode != 0:
            return False
        out = (res.stdout or '').strip()
        return bool(out)
    except Exception:
        return False
