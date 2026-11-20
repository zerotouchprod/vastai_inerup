"""Real-ffmpeg tests: stream-copied AAC must keep every packet after merge."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.infrastructure.video.audio_handler import AudioPreserver, audio_sidecar_name

ffmpeg_bin = shutil.which("ffmpeg")
ffprobe_bin = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(
    not ffmpeg_bin or not ffprobe_bin, reason="ffmpeg/ffprobe not installed"
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _packets(path: Path) -> list[tuple[str, str]]:
    """Return (pts_time, size) for every audio packet, in decode order."""
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "packet=pts_time,size",
            "-of",
            "csv=p=0",
            str(path),
        ]
    ).stdout
    rows = []
    for line in out.splitlines():
        parts = [p for p in line.strip().split(",") if p != ""]
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def _md5_audio(path: Path) -> str:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c",
            "copy",
            "-f",
            "md5",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return raw.split("=")[-1]


def _probe_field(path: Path, stream_sel: str, field: str) -> str:
    return _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            stream_sel,
            "-show_entries",
            f"stream={field}",
            "-of",
            "default=nk=1:nw=1",
            str(path),
        ]
    ).stdout.strip()


def _format_duration(path: Path) -> float:
    return float(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nk=1:nw=1",
                str(path),
            ]
        ).stdout.strip()
    )


def _make_source(path: Path, seconds: float = 3.0, fps: int = 25) -> None:
    """3 s 1080x? small video + AAC-LC 44.1 kHz, long enough to have encoder delay."""
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=320x240:r={fps}:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=44100:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(path),
        ]
    )


def test_extract_and_merge_keeps_every_aac_packet(tmp_path: Path):
    src = tmp_path / "src.mp4"
    _make_source(src)
    src_packets = _packets(src)
    assert len(src_packets) > 50

    preserver = AudioPreserver()
    sidecar = tmp_path / audio_sidecar_name("aac")
    assert preserver.extract_audio(src, sidecar)
    assert _packets(sidecar) == src_packets
    assert _md5_audio(sidecar) == _md5_audio(src)

    # Silent processed video of the same duration (RIFE 2x at 50 fps would also be 3.0 s).
    video = tmp_path / "processed.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=50:d=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video),
        ]
    )
    out = tmp_path / "merged.mp4"
    assert preserver.merge_audio_video(video, sidecar, out)

    out_packets = _packets(out)
    assert out_packets == src_packets
    assert _md5_audio(out) == _md5_audio(src)
    # Video duration stays 3 s; we did not let a timestamp shift stretch or trim the file.
    assert _format_duration(out) == pytest.approx(3.0, abs=0.05)
    assert float(_probe_field(out, "v:0", "duration")) == pytest.approx(3.0, abs=0.05)


def test_shortest_after_make_zero_is_what_drops_trailing_packets(tmp_path: Path):
    """Reproduce the 2026-11-20 prod failure mode, independent of AudioPreserver.

    Remuxing the sidecar with -avoid_negative_ts make_zero shifts AAC priming
    from ~-36 ms to 0 and makes the last packet start after 3.0 s. Muxing that
    with -shortest against a 3.0 s video drops the last two packets.
    """
    src = tmp_path / "src.mp4"
    _make_source(src)
    raw = tmp_path / "raw.m4a"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-c:a",
            "copy",
            "-avoid_negative_ts",
            "disabled",
            str(raw),
        ]
    )
    shifted = tmp_path / "shifted.m4a"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(raw),
            "-c",
            "copy",
            "-avoid_negative_ts",
            "make_zero",
            str(shifted),
        ]
    )
    video = tmp_path / "processed.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=50:d=3",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(video),
        ]
    )
    broken = tmp_path / "broken.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video),
            "-i",
            str(shifted),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-shortest",
            str(broken),
        ]
    )
    src_n = len(_packets(src))
    broken_n = len(_packets(broken))
    assert broken_n < src_n
    # The paid mahoraga clip lost exactly two packets this way (131→129).
    # A lavfi sine may lose one or two depending on priming; require a loss.
    assert src_n - broken_n in (1, 2) or src_n - broken_n >= 1
