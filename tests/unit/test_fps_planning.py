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
