import json
import shutil
import subprocess

import pytest

from src.shared.fps_planning import interp_factor_for, needs_resample, resample_fps


@pytest.mark.parametrize("target,orig,expected", [
    (60, 24, 3),       # 2.5x must round UP (was banker's-rounded to 2 -> 48 fps)
    (60, 30, 2),
    (60, 25, 3),
    (48, 24, 2),
    (30, 24, 2),       # never below 2x
    (120, 24, 5),
    (60, 23.976, 3),
    (72, 24, 3),       # exact multiple stays exact
])
def test_interp_factor_rounds_up(target, orig, expected):
    assert interp_factor_for(target, orig) == expected


def test_interp_factor_rejects_bad_fps():
    with pytest.raises(ValueError):
        interp_factor_for(60, 0)


def test_needs_resample():
    assert needs_resample(72, 60)
    assert not needs_resample(60.0, 60)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_resample_reaches_target_and_keeps_duration(tmp_path):
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=72:d=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    resample_fps(src, dst, 60)
    info = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate:format=duration",
         "-of", "json", str(dst)], capture_output=True, text=True, check=True).stdout)
    num, den = info["streams"][0]["avg_frame_rate"].split("/")
    assert round(int(num) / int(den)) == 60
    assert abs(float(info["format"]["duration"]) - 2.0) < 0.1


from src.shared.fps_planning import is_integer_multiple, plan_output_frames


def test_plan_24_to_60_pattern_and_length():
    plan = plan_output_frames(48, 24, 60)
    assert len(plan) == 120
    # Sample at every target timestamp through the end of the last source-frame interval.
    assert plan[:6] == [(0, 0.0), (0, pytest.approx(0.4)), (0, pytest.approx(0.8)),
                        (1, pytest.approx(0.2)), (1, pytest.approx(0.6)), (2, 0.0)]
    assert plan[-1] == (47, 0.0)  # hold the last source frame through its presentation interval


def test_plan_preserves_full_chunk_frame_count_at_24_to_60():
    # Frame presentation intervals span N/fps, not only the first-to-last PTS span.
    assert len(plan_output_frames(240, 24, 60)) == 600
    assert len(plan_output_frames(293, 24, 60)) == 733


def test_plan_integer_multiple_has_exact_originals():
    plan = plan_output_frames(10, 24, 48)
    assert len(plan) == 20
    assert all((i, 0.0) in plan for i in range(10))
    assert plan[-1] == (9, 0.0)  # hold final source frame for the last target interval
    assert all(0 <= i < 9 for i, f in plan if f > 0.0)


def test_plan_downsampling_never_interpolates_out_of_range():
    plan = plan_output_frames(30, 30, 24)
    assert all(0 <= i <= 29 for i, _ in plan)
    assert plan[-1][0] <= 29


def test_plan_preserves_duration():
    plan = plan_output_frames(48, 24, 60)
    assert abs(len(plan) / 60 - 48 / 24) < 1 / 24 + 1 / 60


def test_is_integer_multiple():
    assert is_integer_multiple(48, 24) and not is_integer_multiple(60, 24)
    assert is_integer_multiple(60, 23.976 * 2.5, 1e-2)
