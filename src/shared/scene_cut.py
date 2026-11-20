"""Scene-cut detection for RIFE interpolation.

RIFE has no built-in awareness of hard cuts: a mid frame synthesised between two unrelated
shots is a morph artefact. When a pair is classified as a cut, callers should hold
(duplicate) the first frame instead of interpolating.

Two signals are combined, both on a 64x64 luminance downscale (Pillow):

* Normalised L1 distance of 32-bin luminance histograms. Hard cuts that rearrange the
  brightness distribution (black vs white, or two unrelated stills) score well above
  DEFAULT_HIST_THRESHOLD. Soft cuts can sit well below it (0.07–0.08 on the mahoraga
  regression clip).
* Mean Gaussian-window SSIM on the same 64x64 gray pair. Soft cuts drop SSIM sharply
  (~0.05–0.11) while same-shot motion stays higher (~0.30+ on that clip).

A pair is a cut when the histogram is already high, *or* when SSIM is low *and* the
histogram has moved at least DEFAULT_HIST_FLOOR. The floor is what keeps a large pan
or a periodic texture translation (identical histogram, low SSIM) from being treated
as a cut. Override with RIFE_SCENE_CUT_THRESHOLD, RIFE_SCENE_CUT_SSIM_THRESHOLD and
RIFE_SCENE_CUT_HIST_FLOOR.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

# L1 distance of 32-bin luminance histograms, normalised to 0..1.
DEFAULT_HIST_THRESHOLD = 0.35
# Back-compat alias used by older tests and callers.
DEFAULT_THRESHOLD = DEFAULT_HIST_THRESHOLD
# Mean SSIM at or below this is a cut, but only if the histogram also moved
# (see DEFAULT_HIST_FLOOR). Tuned on the mahoraga clip: four cuts are 0.046–0.105,
# the nearest non-cut is 0.303, so 0.30 sits in the gap.
DEFAULT_SSIM_THRESHOLD = 0.30
# Minimum histogram L1 required to accept a low-SSIM pair as a cut. Same-shot pans
# and rolled periodic textures keep a nearly identical histogram (~0–0.05).
DEFAULT_HIST_FLOOR = 0.06

_DOWNSCALE = 64
_HIST_BINS = 32
_SSIM_WIN = 11
_SSIM_SIGMA = 1.5
# SSIM constants for 8-bit images (k1=0.01, k2=0.03, L=255).
_SSIM_C1 = (0.01 * 255) ** 2
_SSIM_C2 = (0.03 * 255) ** 2

PathLike = Union[str, Path]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _gray64(path: PathLike) -> np.ndarray:
    image = Image.open(path).convert("L").resize(
        (_DOWNSCALE, _DOWNSCALE), Image.Resampling.BILINEAR
    )
    return np.asarray(image, dtype=np.uint8)


def luminance_histogram(path: PathLike, bins: int = _HIST_BINS) -> np.ndarray:
    gray = _gray64(path)
    counts, _ = np.histogram(gray, bins=bins, range=(0, 256), density=False)
    total = max(1, int(counts.sum()))
    return (counts.astype(np.float64) / total).astype(np.float64)


def histogram_l1_distance(path_a: PathLike, path_b: PathLike) -> float:
    """Normalised L1 distance in [0, 1] between the two luminance histograms."""
    a = luminance_histogram(path_a)
    b = luminance_histogram(path_b)
    return float(np.abs(a - b).sum()) / 2.0


def _gaussian_kernel(win: int = _SSIM_WIN, sigma: float = _SSIM_SIGMA) -> np.ndarray:
    axis = np.arange(win, dtype=np.float64) - (win // 2)
    kernel = np.exp(-(axis ** 2) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    return kernel


def _separable_conv(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    # reflect-pad so the window is defined at the borders of a 64x64 frame
    pad = len(kernel) // 2
    padded = np.pad(image, pad, mode="reflect")
    tmp = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), -1, padded)
    return np.apply_along_axis(lambda col: np.convolve(col, kernel, mode="valid"), -2, tmp)


def ssim_gray(a: np.ndarray, b: np.ndarray) -> float:
    """Mean Gaussian-window SSIM of two 2-D uint8 (or float 0–255) images."""
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    kernel = _gaussian_kernel()
    mu1 = _separable_conv(a, kernel)
    mu2 = _separable_conv(b, kernel)
    sigma1 = _separable_conv(a * a, kernel) - mu1 ** 2
    sigma2 = _separable_conv(b * b, kernel) - mu2 ** 2
    sigma12 = _separable_conv(a * b, kernel) - mu1 * mu2
    num = (2 * mu1 * mu2 + _SSIM_C1) * (2 * sigma12 + _SSIM_C2)
    den = (mu1 ** 2 + mu2 ** 2 + _SSIM_C1) * (sigma1 + sigma2 + _SSIM_C2)
    return float((num / den).mean())


def ssim_distance(path_a: PathLike, path_b: PathLike) -> float:
    """Mean SSIM of the 64x64 luminance downscales of the two frames."""
    return ssim_gray(_gray64(path_a), _gray64(path_b))


def pair_metrics(path_a: PathLike, path_b: PathLike) -> dict:
    """Histogram L1 and SSIM for one pair (one downscale each)."""
    a = _gray64(path_a)
    b = _gray64(path_b)
    counts_a, _ = np.histogram(a, bins=_HIST_BINS, range=(0, 256), density=False)
    counts_b, _ = np.histogram(b, bins=_HIST_BINS, range=(0, 256), density=False)
    hist = float(np.abs(counts_a.astype(np.float64) / max(1, int(counts_a.sum()))
                        - counts_b.astype(np.float64) / max(1, int(counts_b.sum()))).sum()) / 2.0
    return {"hist_l1": hist, "ssim": ssim_gray(a, b)}


def is_scene_cut(
    path_a: PathLike,
    path_b: PathLike,
    threshold: float | None = None,
    *,
    ssim_threshold: float | None = None,
    hist_floor: float | None = None,
) -> bool:
    """True when the pair should not be interpolated.

    `threshold` is the hard-cut histogram L1 (same meaning as before this change).
    """
    hist_hi = DEFAULT_HIST_THRESHOLD if threshold is None else threshold
    ssim_lo = (
        DEFAULT_SSIM_THRESHOLD
        if ssim_threshold is None
        else ssim_threshold
    )
    floor = DEFAULT_HIST_FLOOR if hist_floor is None else hist_floor
    # Env overrides apply only when the caller did not pass an explicit value,
    # so existing tests that pass `threshold=` keep a stable meaning.
    if threshold is None:
        hist_hi = _env_float("RIFE_SCENE_CUT_THRESHOLD", hist_hi)
    if ssim_threshold is None:
        ssim_lo = _env_float("RIFE_SCENE_CUT_SSIM_THRESHOLD", ssim_lo)
    if hist_floor is None:
        floor = _env_float("RIFE_SCENE_CUT_HIST_FLOOR", floor)
    try:
        metrics = pair_metrics(path_a, path_b)
    except OSError:
        # Unreadable/missing frames: let the interpolator raise a clearer error (or a test mock run).
        return False
    if metrics["hist_l1"] >= hist_hi:
        return True
    return metrics["ssim"] <= ssim_lo and metrics["hist_l1"] >= floor


def integer_factor_frame_count(n_src: int, factor: int) -> int:
    """Output length for integer-factor RIFE: N originals + (factor-1)*N held/interpolated = factor*N.

    Interpolating only between frames yields factor*N - (factor-1) (the classic 2N-1 at 2x), which
    shortens a 20 s / 30 fps clip to 19.983 s at 60 fps. The last source frame is held (factor-1)
    extra times so duration stays n_src / src_fps.
    """
    if n_src < 1 or factor < 2:
        raise ValueError("n_src must be >= 1 and factor >= 2")
    return n_src * int(factor)
