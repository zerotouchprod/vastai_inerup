"""Auto-batch estimation (output pixels / free VRAM) and OOM step-down recovery.

No GPU or torch needed: CUDA OOM is simulated with a fake exception class.
"""

import logging
from types import SimpleNamespace

import pytest

from src.infrastructure.processors.realesrgan import native as n

GIB = 2**30
OUT_4K_PORTRAIT = (3840, 2160)  # (h, w) for 1080x1920 input x2


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (
        "REAL_ESRGAN_MAX_BATCH_SIZE",
        "REAL_ESRGAN_VRAM_HEADROOM",
        "REAL_ESRGAN_PEAK_BYTES_PER_OUT_PIXEL",
        "REAL_ESRGAN_OOM_MAX_RETRIES",
        "REAL_ESRGAN_MAX_BATCH_PIXELS",
    ):
        monkeypatch.delenv(k, raising=False)
    n.clear_safe_batches()
    yield
    n.clear_safe_batches()


def test_per_frame_peak_matches_observed_4080_oom():
    _, d = n.estimate_auto_batch(*OUT_4K_PORTRAIT, "RealESRGAN_x2plus", 16 * GIB)
    # (11.31 + 7.91) GiB / 8 frames observed on instance 58412911
    assert d["per_frame_gib"] == pytest.approx(2.40, abs=0.05)


@pytest.mark.parametrize(
    "free_gib,expected",
    [(15.2, 5), (14.0, 4), (23.2, 8), (40.0, 8), (2.0, 1), (0.0, 1)],
)
def test_estimate_by_output_pixels(free_gib, expected):
    batch, _ = n.estimate_auto_batch(
        *OUT_4K_PORTRAIT, "RealESRGAN_x2plus", free_gib * GIB
    )
    assert batch == expected


def test_16gb_never_gets_batch_8_at_4k_output():
    batch, _ = n.estimate_auto_batch(*OUT_4K_PORTRAIT, "RealESRGAN_x2plus", 15.6 * GIB)
    assert batch * 2.40 <= 15.6 * 0.85


def test_cap_headroom_and_fp32_are_configurable(monkeypatch):
    monkeypatch.setenv("REAL_ESRGAN_MAX_BATCH_SIZE", "3")
    assert (
        n.estimate_auto_batch(*OUT_4K_PORTRAIT, "RealESRGAN_x2plus", 40 * GIB)[0] == 3
    )
    monkeypatch.delenv("REAL_ESRGAN_MAX_BATCH_SIZE")
    monkeypatch.setenv("REAL_ESRGAN_VRAM_HEADROOM", "0.5")
    assert (
        n.estimate_auto_batch(*OUT_4K_PORTRAIT, "RealESRGAN_x2plus", 23.2 * GIB)[0] == 4
    )
    monkeypatch.delenv("REAL_ESRGAN_VRAM_HEADROOM")
    assert (
        n.estimate_auto_batch(
            *OUT_4K_PORTRAIT, "RealESRGAN_x2plus", 23.2 * GIB, half=False
        )[0]
        == 4
    )


def test_small_output_hits_cap():
    batch, d = n.estimate_auto_batch(1080, 1920, "RealESRGAN_x2plus", 15.2 * GIB)
    assert batch == 8 and d["raw"] > 8


class FakeOOM(Exception):
    pass


def _proc(monkeypatch, batch=8, explicit=None):
    monkeypatch.setattr(n, "_is_cuda_oom", lambda exc: isinstance(exc, FakeOOM))
    p = n.RealESRGANNative.__new__(n.RealESRGANNative)
    p.scale = 2
    p.model_name = "RealESRGAN_x2plus"
    p.tile_size = 0
    p.batch_size = batch
    p._explicit_batch_size = explicit
    p._oom_recovery_attempted = False
    p._oom_batch_cap = None
    p._oom_events = []
    p._safe_key = n.safe_batch_key("RTX 4080", "RealESRGAN_x2plus", 2160, 3840)
    p._upsampler = SimpleNamespace(scale=2, tile=0)
    p.logger = logging.getLogger("test")
    p.tiled_calls = []

    def enhance(img, idx=None):
        p.tiled_calls.append(idx)
        return ("tiled", img)

    p._enhance_frame = enhance
    return p


def _fake_forward(max_ok, calls):
    def fwd(upsampler, frames, scale, timing=None):
        calls.append(len(frames))
        if len(frames) > max_ok:
            raise FakeOOM("CUDA out of memory")
        return [("out", f) for f in frames]

    return fwd


def test_step_down_8_4_2_retries_same_frames_without_tiling(monkeypatch):
    p = _proc(monkeypatch)
    calls = []
    monkeypatch.setattr(n, "batch_forward", _fake_forward(2, calls))
    frames = list(range(8))

    out = p._upscale_loaded(frames)

    assert out == [("out", f) for f in frames]  # every frame once, in order
    assert calls == [8, 4, 2, 2, 2, 2]
    assert p.tile_size == 0 and p.tiled_calls == []
    assert p._gpu_batch_size() == 2
    assert [e["to_batch"] for e in p._oom_events] == [4, 2]
    assert n.safe_batch_snapshot() == [
        {
            "gpu": "RTX 4080",
            "model": "RealESRGAN_x2plus",
            "output_resolution": "2160x3840",
            "batch": 2,
            "tile": 0,
        }
    ]


def test_explicit_batch_also_steps_down(monkeypatch):
    p = _proc(monkeypatch, batch=1, explicit=4)
    calls = []
    monkeypatch.setattr(n, "batch_forward", _fake_forward(2, calls))
    assert len(p._upscale_loaded(list(range(4)))) == 4
    assert calls == [4, 2, 2]


def test_tiling_only_after_batch_1_ooms(monkeypatch):
    p = _proc(monkeypatch, batch=2)
    calls = []
    monkeypatch.setattr(n, "batch_forward", _fake_forward(0, calls))
    p._frame_base = 10

    out = p._upscale_loaded(["a", "b"])

    assert calls == [2, 1]
    assert p.tile_size == 512 and p.oom_fallback is True
    assert out == [("tiled", "a"), ("tiled", "b")]
    assert p.tiled_calls == [10, 11]
    assert n.safe_batch_snapshot()[0]["tile"] == 512


def test_recovery_is_bounded(monkeypatch):
    monkeypatch.setenv("REAL_ESRGAN_OOM_MAX_RETRIES", "2")
    p = _proc(monkeypatch, batch=8)
    calls = []
    monkeypatch.setattr(n, "batch_forward", _fake_forward(0, calls))
    with pytest.raises(RuntimeError, match="bounded retries"):
        p._upscale_loaded(list(range(8)))
    assert calls == [8, 4, 2]


def test_non_oom_errors_propagate(monkeypatch):
    p = _proc(monkeypatch)

    def boom(*a, **k):
        raise ValueError("bad")

    monkeypatch.setattr(n, "batch_forward", boom)
    with pytest.raises(ValueError):
        p._upscale_loaded([1, 2])


def test_learned_safe_batch_caps_next_chunk(monkeypatch):
    monkeypatch.setattr(n, "_gpu_name", lambda: "RTX 4080")
    monkeypatch.setattr(n, "_free_vram_bytes", lambda: int(15.2 * GIB))
    n.remember_safe_batch(
        n.safe_batch_key("RTX 4080", "RealESRGAN_x2plus", 2160, 3840), 2, 0
    )
    p = _proc(monkeypatch)
    p._safe_key = None
    p._batch_configured_for_resolution = False

    p._configure_batch_for_resolution(1920, 1080)

    assert p.batch_size == 5  # estimate
    assert p._gpu_batch_size() == 2  # capped by what this process learned
    assert p.batch_source == "auto_vram+learned"


def test_auto_estimate_used_with_cuda_info(monkeypatch):
    monkeypatch.setattr(n, "_gpu_name", lambda: "RTX 3090")
    monkeypatch.setattr(n, "_free_vram_bytes", lambda: int(23.2 * GIB))
    p = _proc(monkeypatch)
    p._batch_configured_for_resolution = False
    p._configure_batch_for_resolution(1920, 1080)
    assert p._gpu_batch_size() == 8 and p.batch_source == "auto_vram"


def test_fps_meter_separates_warmup_from_steady_state():
    m = n.FpsMeter(start=0.0, window=10)
    m.mark(8, now=10.0)  # first group: model warmup + OOM ~10 s
    for i in range(1, 21):
        m.mark(8 + i, now=10.0 + i * 0.68)
    assert m.cumulative() == pytest.approx(28 / 23.6, rel=1e-3)
    assert m.steady() == pytest.approx(1 / 0.68, rel=1e-3)
    assert m.recent() == pytest.approx(1 / 0.68, rel=1e-3)


def test_alloc_conf_default_is_set_but_env_overridable():
    import os
    import subprocess
    import sys

    code = (
        "import os, src.infrastructure.processors.realesrgan.native;"
        "print(os.environ['PYTORCH_CUDA_ALLOC_CONF'])"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTORCH_CUDA_ALLOC_CONF"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.stdout.strip() == "expandable_segments:True", out.stderr
    env["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128"
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.stdout.strip() == "max_split_size_mb:128", out.stderr


def test_worker_collects_upscale_stats_for_complete_payload():
    from src.worker import processors

    n.LAST_UPSCALE_STATS.update({"final_gpu_batch": 2, "fps_steady": 1.47})
    task = {}
    processors._collect_upscale_stats(task)
    assert task["_upscale"] == {"final_gpu_batch": 2, "fps_steady": 1.47}
    assert n.LAST_UPSCALE_STATS == {}  # not leaked into the next chunk
    other = {}
    processors._collect_upscale_stats(other)
    assert "_upscale" not in other


def test_client_sends_upscale_outside_numeric_timings(monkeypatch):
    from src.worker.client import ControlPlaneClient as WorkerClient

    sent = {}
    c = WorkerClient.__new__(WorkerClient)
    monkeypatch.setattr(c, "_claim_request_id", lambda a: "cr", raising=False)
    monkeypatch.setattr(
        c, "_post", lambda path, payload: sent.update(payload) or {}, raising=False
    )
    monkeypatch.setattr(c, "_owned", lambda r: None, raising=False)
    c.complete("a1", "out.mp4", {"process_s": 1.0}, upscale={"final_gpu_batch": 2})
    assert sent["timings"] == {"process_s": 1.0}
    assert sent["upscale"] == {"final_gpu_batch": 2}
