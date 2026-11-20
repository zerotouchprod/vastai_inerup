from pathlib import Path

import pytest

import numpy as np
from PIL import Image

from src.shared.scene_cut import (
    DEFAULT_HIST_FLOOR,
    DEFAULT_HIST_THRESHOLD,
    DEFAULT_SSIM_THRESHOLD,
    histogram_l1_distance,
    integer_factor_frame_count,
    is_scene_cut,
    pair_metrics,
    ssim_distance,
    ssim_gray,
)
from src.shared.fps_planning import plan_output_frames


def _write(path: Path, color) -> Path:
    Image.new("RGB", (32, 32), color).save(path)
    return path


def test_integer_factor_frame_count_is_factor_times_n():
    assert integer_factor_frame_count(600, 2) == 1200
    assert integer_factor_frame_count(600, 4) == 2400
    # The unfixed "only interpolate between frames" count:
    assert 2 * 600 - 1 == 1199


def test_plan_output_frames_for_exact_2x_covers_duration():
    plan = plan_output_frames(600, 30.0, 60.0)
    assert len(plan) == 1200
    assert plan[0] == (0, 0.0)
    assert plan[-1][0] == 599
    assert plan[-1][1] == 0.0


def test_hard_cut_is_detected_and_similar_frames_are_not(tmp_path: Path):
    black = _write(tmp_path / "black.png", (0, 0, 0))
    white = _write(tmp_path / "white.png", (255, 255, 255))
    gray_a = _write(tmp_path / "gray_a.png", (128, 128, 128))
    gray_b = _write(tmp_path / "gray_b.png", (130, 129, 127))

    assert histogram_l1_distance(black, white) >= 0.9
    assert is_scene_cut(black, white)
    assert histogram_l1_distance(gray_a, gray_b) < 0.1
    assert not is_scene_cut(gray_a, gray_b)


def test_noise_frames_from_one_shot_are_not_cuts(tmp_path: Path):
    rng = np.random.default_rng(0)
    base = rng.integers(80, 160, size=(48, 48, 3), dtype=np.uint8)
    a = tmp_path / "shot_a.png"
    b = tmp_path / "shot_b.png"
    Image.fromarray(base, "RGB").save(a)
    Image.fromarray(
        np.clip(
            base.astype(np.int16) + rng.integers(-4, 5, size=base.shape), 0, 255
        ).astype(np.uint8),
        "RGB",
    ).save(b)
    assert not is_scene_cut(a, b)


# --- combined SSIM + histogram detector (mahoraga regression + motion) ---

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "fixtures" / "scene_cut" / "mahoraga_64"
)
# 0-based indices of the first frame of each known cut in the 25 fps source.
MAHORAGA_CUTS = ((24, 25), (25, 26), (26, 27), (55, 56))


def _mahoraga_frame(index: int) -> Path:
    path = FIXTURE_DIR / f"{index + 1:04d}.png"
    assert path.exists(), f"missing fixture {path}"
    return path


def test_mahoraga_metrics_match_expected_ranges():
    """Evidence for the chosen thresholds; fails if fixtures or the metric change silently."""
    # hist L1 / SSIM measured on these exact 64x64 fixtures (see PR description).
    expected = {
        (24, 25): {"hist_l1": (0.06, 0.12), "ssim": (0.04, 0.15)},
        (25, 26): {"hist_l1": (0.06, 0.12), "ssim": (0.02, 0.12)},
        (26, 27): {"hist_l1": (0.30, 0.50), "ssim": (0.02, 0.12)},
        (55, 56): {"hist_l1": (0.60, 0.85), "ssim": (0.05, 0.18)},
    }
    for (a, b), bounds in expected.items():
        m = pair_metrics(_mahoraga_frame(a), _mahoraga_frame(b))
        assert bounds["hist_l1"][0] <= m["hist_l1"] <= bounds["hist_l1"][1], (a, b, m)
        assert bounds["ssim"][0] <= m["ssim"] <= bounds["ssim"][1], (a, b, m)
        # The two soft cuts stay below the legacy histogram-only threshold.
        if (a, b) in ((24, 25), (25, 26)):
            assert m["hist_l1"] < DEFAULT_HIST_THRESHOLD


def test_mahoraga_all_four_cuts_detected_and_no_false_positives():
    frames = sorted(FIXTURE_DIR.glob("*.png"))
    assert len(frames) == 75
    detected = []
    for i in range(len(frames) - 1):
        if is_scene_cut(frames[i], frames[i + 1]):
            detected.append((i, i + 1))
    assert tuple(detected) == MAHORAGA_CUTS


def test_legacy_histogram_threshold_still_misses_soft_cuts():
    for a, b in ((24, 25), (25, 26)):
        m = pair_metrics(_mahoraga_frame(a), _mahoraga_frame(b))
        assert m["hist_l1"] < DEFAULT_HIST_THRESHOLD
        # Force SSIM off the table: only the histogram high threshold would fire.
        assert not is_scene_cut(
            _mahoraga_frame(a),
            _mahoraga_frame(b),
            threshold=DEFAULT_HIST_THRESHOLD,
            ssim_threshold=-1.0,
            hist_floor=1.0,
        )
        assert is_scene_cut(_mahoraga_frame(a), _mahoraga_frame(b))


def test_fast_motion_with_stable_histogram_is_not_a_cut(tmp_path: Path):
    """A large pan / rolled periodic texture has low SSIM but an almost-identical histogram."""
    yy, xx = np.mgrid[0:64, 0:64]
    base = ((np.sin(xx / 3.0) + np.sin(yy / 5.0)) * 127 + 128).astype(np.uint8)
    shifted = np.roll(base, 8, axis=1)
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.fromarray(base, mode="L").save(a)
    Image.fromarray(shifted, mode="L").save(b)
    m = pair_metrics(a, b)
    assert m["ssim"] <= DEFAULT_SSIM_THRESHOLD
    assert m["hist_l1"] < DEFAULT_HIST_FLOOR
    assert not is_scene_cut(a, b)


def test_ssim_of_identical_frames_is_one(tmp_path: Path):
    path = tmp_path / "same.png"
    Image.new("L", (48, 48), 80).save(path)
    assert ssim_distance(path, path) == pytest.approx(1.0, abs=1e-6)
    assert ssim_gray(
        np.full((32, 32), 80, dtype=np.uint8), np.full((32, 32), 80, dtype=np.uint8)
    ) == pytest.approx(1.0, abs=1e-6)
