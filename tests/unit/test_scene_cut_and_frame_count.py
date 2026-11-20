from pathlib import Path

import numpy as np
from PIL import Image

from src.shared.scene_cut import (
    histogram_l1_distance,
    integer_factor_frame_count,
    is_scene_cut,
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
