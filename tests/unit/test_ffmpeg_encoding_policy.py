from pathlib import Path
from unittest.mock import Mock

from src.infrastructure.media.ffmpeg import FFmpegWrapper


def test_nvenc_default_quality_policy_avoids_unbounded_cq19(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-encoders" in cmd:
            return Mock(stdout="h264_nvenc", stderr="")
        output.write_bytes(b"encoded")
        return Mock(stdout="", stderr="")

    wrapper = FFmpegWrapper()
    monkeypatch.setattr("src.infrastructure.media.ffmpeg.subprocess.run", run)
    monkeypatch.setattr(wrapper, "get_duration", lambda _: 1.0)
    monkeypatch.setattr(wrapper, "get_fps", lambda _: 1.0)

    wrapper.assemble_video(frames, output, fps=1.0, encoder="h264_nvenc")

    encode = next(cmd for cmd in calls if "-c:v" in cmd)
    assert encode[encode.index("-cq") + 1] == "23"
    assert "-b:v" not in encode
    assert "-maxrate" not in encode


def test_nvenc_quality_override_is_explicit(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-encoders" in cmd:
            return Mock(stdout="h264_nvenc", stderr="")
        output.write_bytes(b"encoded")
        return Mock(stdout="", stderr="")

    wrapper = FFmpegWrapper()
    monkeypatch.setattr("src.infrastructure.media.ffmpeg.subprocess.run", run)
    monkeypatch.setattr(wrapper, "get_duration", lambda _: 1.0)
    monkeypatch.setattr(wrapper, "get_fps", lambda _: 1.0)

    wrapper.assemble_video(frames, output, fps=1.0, encoder="h264_nvenc", quality=20)

    encode = next(cmd for cmd in calls if "-c:v" in cmd)
    assert encode[encode.index("-cq") + 1] == "20"
