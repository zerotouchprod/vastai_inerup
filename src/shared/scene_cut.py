"""Scene-cut detection for RIFE interpolation.

RIFE has no built-in awareness of hard cuts: a mid frame synthesised between two unrelated
shots is a morph artefact. When the histogram distance between a pair exceeds the threshold,
callers should hold (duplicate) the first frame instead of interpolating.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

# L1 distance of 32-bin luminance histograms, normalised to 0..1. Tuned so a hard cut
# (black vs white, or two unrelated stills) is well above, and consecutive frames of one
# shot stay below. Override with RIFE_SCENE_CUT_THRESHOLD if needed.
DEFAULT_THRESHOLD = 0.35

PathLike = Union[str, Path]


def luminance_histogram(path: PathLike, bins: int = 32) -> np.ndarray:
    image = Image.open(path).convert("L").resize((64, 64), Image.Resampling.BILINEAR)
    counts, _ = np.histogram(
        np.asarray(image, dtype=np.uint8), bins=bins, range=(0, 256), density=False
    )
    total = max(1, int(counts.sum()))
    hist = counts.astype(np.float64) / total
    return hist.astype(np.float64)


def histogram_l1_distance(path_a: PathLike, path_b: PathLike) -> float:
    """Normalised L1 distance in [0, 1] between the two luminance histograms."""
    a = luminance_histogram(path_a)
    b = luminance_histogram(path_b)
    return float(np.abs(a - b).sum()) / 2.0


def is_scene_cut(
    path_a: PathLike, path_b: PathLike, threshold: float = DEFAULT_THRESHOLD
) -> bool:
    return histogram_l1_distance(path_a, path_b) >= threshold


def integer_factor_frame_count(n_src: int, factor: int) -> int:
    """Output length for integer-factor RIFE: N originals + (factor-1)*N held/interpolated = factor*N.

    Interpolating only between frames yields factor*N - (factor-1) (the classic 2N-1 at 2x), which
    shortens a 20 s / 30 fps clip to 19.983 s at 60 fps. The last source frame is held (factor-1)
    extra times so duration stays n_src / src_fps.
    """
    if n_src < 1 or factor < 2:
        raise ValueError("n_src must be >= 1 and factor >= 2")
    return n_src * int(factor)
