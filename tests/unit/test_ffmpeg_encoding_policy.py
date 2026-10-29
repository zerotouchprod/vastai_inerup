from unittest.mock import Mock

from src.infrastructure.media.assembler import FFmpegAssembler
from src.infrastructure.media.ffmpeg import FFmpegWrapper


def _mock_nvenc_run(output, calls, encoder):
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-encoders" in cmd:
            return Mock(stdout=encoder, stderr="")
        output.write_bytes(b"encoded")
        return Mock(stdout="", stderr="")

    return run


def test_nvenc_default_quality_policy_avoids_unbounded_cq19(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    calls = []

    wrapper = FFmpegWrapper()
    monkeypatch.setattr(
        "src.infrastructure.media.ffmpeg.subprocess.run",
        _mock_nvenc_run(output, calls, "h264_nvenc"),
    )
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

    wrapper = FFmpegWrapper()
    monkeypatch.setattr(
        "src.infrastructure.media.ffmpeg.subprocess.run",
        _mock_nvenc_run(output, calls, "h264_nvenc"),
    )
    monkeypatch.setattr(wrapper, "get_duration", lambda _: 1.0)
    monkeypatch.setattr(wrapper, "get_fps", lambda _: 1.0)

    wrapper.assemble_video(frames, output, fps=1.0, encoder="h264_nvenc", quality=20)

    encode = next(cmd for cmd in calls if "-c:v" in cmd)
    assert encode[encode.index("-cq") + 1] == "20"


def test_hevc_nvenc_uses_quality_override_and_zero_is_not_auto(tmp_path, monkeypatch):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    calls = []

    wrapper = FFmpegWrapper()
    monkeypatch.setattr(
        "src.infrastructure.media.ffmpeg.subprocess.run",
        _mock_nvenc_run(output, calls, "hevc_nvenc"),
    )
    monkeypatch.setattr(wrapper, "get_duration", lambda _: 1.0)
    monkeypatch.setattr(wrapper, "get_fps", lambda _: 1.0)

    wrapper.assemble_video(frames, output, fps=1.0, encoder="hevc_nvenc", quality=0)

    encode = next(cmd for cmd in calls if "-c:v" in cmd)
    assert encode[encode.index("-cq") + 1] == "1"


def test_assembler_forwards_quality_override(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    frame = frames / "frame_000001.png"
    frame.write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    assembler = FFmpegAssembler()
    assembler._ffmpeg.assemble_video = Mock(return_value=output)

    assembler.assemble([frame], output, fps=1.0, encoder="h264_nvenc", quality=21)

    assert assembler._ffmpeg.assemble_video.call_args.kwargs["quality"] == 21
