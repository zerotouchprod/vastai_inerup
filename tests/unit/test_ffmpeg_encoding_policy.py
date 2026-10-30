from unittest.mock import Mock

import pytest

from src.infrastructure.media.assembler import FFmpegAssembler
from src.infrastructure.media.ffmpeg import (
    NVENC_DEFAULTS,
    FFmpegWrapper,
    nvenc_encode_args,
)


def _mock_nvenc_run(output, calls, encoder):
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-encoders" in cmd:
            return Mock(stdout=encoder, stderr="")
        output.write_bytes(b"encoded")
        return Mock(stdout="", stderr="")

    return run


def _encode_cmd(tmp_path, monkeypatch, encoder="h264_nvenc", fps=30.0, **kw):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_000001.png").write_bytes(b"frame")
    output = tmp_path / "out.mp4"
    calls = []
    wrapper = FFmpegWrapper()
    monkeypatch.setattr(
        "src.infrastructure.media.ffmpeg.subprocess.run",
        _mock_nvenc_run(output, calls, encoder),
    )
    monkeypatch.setattr(wrapper, "get_duration", lambda _: 1.0)
    monkeypatch.setattr(wrapper, "get_fps", lambda _: fps)
    wrapper.assemble_video(frames, output, fps=fps, encoder=encoder, **kw)
    return next(cmd for cmd in calls if "-c:v" in cmd)


def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


@pytest.fixture(autouse=True)
def _clean_nvenc_env(monkeypatch):
    for k in NVENC_DEFAULTS:
        monkeypatch.delenv(k, raising=False)


def test_nvenc_default_is_capped_vbr(tmp_path, monkeypatch):
    cmd = _encode_cmd(tmp_path, monkeypatch)
    assert _arg(cmd, "-preset") == "p6"
    assert _arg(cmd, "-tune") == "hq"
    assert _arg(cmd, "-rc") == "vbr"
    assert _arg(cmd, "-cq") == "24"
    assert _arg(cmd, "-b:v") == "0"
    assert _arg(cmd, "-maxrate") == "30M"
    assert _arg(cmd, "-bufsize") == "60M"
    assert _arg(cmd, "-spatial-aq") == "1"
    assert _arg(cmd, "-g") == "60"
    assert _arg(cmd, "-profile:v") == "high"
    assert _arg(cmd, "-pix_fmt") == "yuv420p"


def test_nvenc_legacy_mode_restores_uncapped_cq(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVIDUP_NVENC_RC_MODE", "legacy")
    cmd = _encode_cmd(tmp_path, monkeypatch)
    assert _arg(cmd, "-cq") == "23"
    for flag in ("-b:v", "-maxrate", "-rc", "-tune", "-profile:v", "-g"):
        assert flag not in cmd


def test_nvenc_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVIDUP_NVENC_CQ", "26")
    monkeypatch.setenv("AIVIDUP_NVENC_MAXRATE", "20M")
    monkeypatch.setenv("AIVIDUP_NVENC_BUFSIZE", "40M")
    monkeypatch.setenv("AIVIDUP_NVENC_GOP_SECONDS", "1")
    monkeypatch.setenv("AIVIDUP_NVENC_SPATIAL_AQ", "0")
    cmd = _encode_cmd(tmp_path, monkeypatch, fps=60.0)
    assert (_arg(cmd, "-cq"), _arg(cmd, "-maxrate"), _arg(cmd, "-bufsize")) == (
        "26",
        "20M",
        "40M",
    )
    assert _arg(cmd, "-g") == "60"
    assert _arg(cmd, "-spatial-aq") == "0"


def test_nvenc_unknown_mode_falls_back_to_capped():
    args = nvenc_encode_args(
        "h264_nvenc", None, 30, env={"AIVIDUP_NVENC_RC_MODE": "cbr"}
    )
    assert args[args.index("-maxrate") + 1] == "30M"


def test_hevc_capped_has_no_h264_profile():
    args = nvenc_encode_args("hevc_nvenc", None, 30, env={})
    assert "-profile:v" not in args and "-maxrate" in args


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
