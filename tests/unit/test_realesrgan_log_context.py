import io
import logging

from src.infrastructure.processors.realesrgan.native import (
    RealESRGANNative,
    _TilePrintFilter,
)


def test_tile_prints_are_swallowed_and_counted():
    out = io.StringIO()
    f = _TilePrintFilter(out)
    for i in range(12):
        print(f"\tTile {i + 1}/12", file=f)
    print("other line", file=f)
    f.flush()
    assert f.tiles_seen == 12 and f.tiles_total == 12
    assert out.getvalue() == "other line\n"


def test_oom_warning_has_before_after_and_reason(monkeypatch, caplog):
    monkeypatch.setenv("AIVIDUP_LOG_JOB_ID", "job-1")
    monkeypatch.setenv("AIVIDUP_LOG_CHUNK_ID", "7")
    p = RealESRGANNative.__new__(RealESRGANNative)
    p.tile_size = 0
    p.batch_size = 2
    p._explicit_batch_size = 2
    p._oom_recovery_attempted = False
    p._upsampler = None
    p.settings_source = {"tile": "env"}
    p.tile_reason = "env"
    p.logger = logging.getLogger("t")
    with caplog.at_level(logging.WARNING):
        p._recover_from_oom(2)
    msg = caplog.records[-1].getMessage()
    assert "OOM FALLBACK job=job-1 chunk=7" in msg
    assert "tile 0(env) -> 512(oom)" in msg and "gpu_batch 2 -> 1" in msg
    assert p.tile_reason == "oom" and p.oom_fallback is True
