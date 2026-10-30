"""GPU-specific Real-ESRGAN performance profiles: selection, precedence, OOM, job scoping.

No GPU or torch needed.
"""

import logging
from types import SimpleNamespace

import pytest

from src.infrastructure.processors.realesrgan import native as n
from src.infrastructure.processors.realesrgan import profiles as pr

GIB = 2**30
X2 = "RealESRGAN_x2plus"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (
        "REAL_ESRGAN_PROFILES",
        "REAL_ESRGAN_PROFILES_FILE",
        "REAL_ESRGAN_MAX_BATCH_SIZE",
        "REAL_ESRGAN_VRAM_HEADROOM",
        "REAL_ESRGAN_OOM_MAX_RETRIES",
    ):
        monkeypatch.delenv(k, raising=False)
    n.clear_safe_batches()
    yield
    n.clear_safe_batches()


# ---- file + matching -------------------------------------------------------


def test_shipped_file_parses_and_has_measured_profiles():
    ids = {p.id: p for p in pr.load_profiles(pr.DEFAULT_PROFILES_FILE)}
    p4080 = ids["rtx4080-x2plus-fp16-1080x1920"]
    p3090 = ids["rtx3090-x2plus-fp16-1080x1920"]
    assert (p4080.tile, p4080.gpu_batch, p4080.reference_fps) == (512, 1, 1.27)
    assert (p3090.tile, p3090.gpu_batch, p3090.reference_fps) == (0, 2, 1.14)


@pytest.mark.parametrize(
    "raw,norm",
    [
        ("NVIDIA GeForce RTX 4080", "RTX 4080"),
        ("RTX 4080", "RTX 4080"),
        ("rtx_4080", "RTX 4080"),
        ("NVIDIA GeForce RTX 4080 SUPER", "RTX 4080 SUPER"),
        ("NVIDIA GeForce RTX 3090", "RTX 3090"),
        ("NVIDIA L4", "L4"),
    ],
)
def test_normalize_gpu_name(raw, norm):
    assert pr.normalize_gpu_name(raw) == norm


def test_4080_and_3090_pick_different_modes():
    a = pr.select_profile("NVIDIA GeForce RTX 4080", X2, 2, 1080, 1920, True)
    b = pr.select_profile("NVIDIA GeForce RTX 3090", X2, 2, 1080, 1920, True)
    assert (a.tile, a.gpu_batch) == (512, 1)
    assert (b.tile, b.gpu_batch) == (0, 2)


@pytest.mark.parametrize(
    "gpu,model,scale,w,h,half",
    [
        ("NVIDIA L4", X2, 2, 1080, 1920, True),  # unknown GPU
        ("NVIDIA GeForce RTX 4080 SUPER", X2, 2, 1080, 1920, True),  # different GPU
        ("NVIDIA GeForce RTX 4080 Laptop GPU", X2, 2, 1080, 1920, True),
        ("NVIDIA GeForce RTX 4080", X2, 2, 1920, 1080, True),  # landscape: not measured
        ("NVIDIA GeForce RTX 4080", X2, 2, 720, 1280, True),  # other resolution
        ("NVIDIA GeForce RTX 4080", X2, 2, 2160, 3840, True),  # 4K input
        ("NVIDIA GeForce RTX 4080", "RealESRGAN_x4plus", 4, 1080, 1920, True),
        ("NVIDIA GeForce RTX 4080", X2, 2, 1080, 1920, False),  # fp32
    ],
)
def test_no_profile_outside_measured_key(gpu, model, scale, w, h, half):
    assert pr.select_profile(gpu, model, scale, w, h, half) is None


def test_disable_and_override_file(monkeypatch, tmp_path):
    monkeypatch.setenv("REAL_ESRGAN_PROFILES", "off")
    assert pr.select_profile("RTX 4080", X2, 2, 1080, 1920) is None
    monkeypatch.delenv("REAL_ESRGAN_PROFILES")
    f = tmp_path / "p.yaml"
    f.write_text(
        "profiles:\n  - {id: l4-test, gpu: NVIDIA L4, model: RealESRGAN_x2plus,"
        " scale: 2, input: 720x1280, tile: 256, gpu_batch: 1}\n"
    )
    monkeypatch.setenv("REAL_ESRGAN_PROFILES_FILE", str(f))
    assert pr.select_profile("NVIDIA L4", X2, 2, 720, 1280).id == "l4-test"
    assert pr.select_profile("RTX 4080", X2, 2, 1080, 1920) is None


def test_invalid_profiles_rejected():
    with pytest.raises(ValueError):
        pr.parse_profiles(
            {
                "profiles": [
                    {
                        "id": "x",
                        "gpu": "a",
                        "model": X2,
                        "scale": 2,
                        "input": "1080",
                        "tile": 0,
                        "gpu_batch": 1,
                    }
                ]
            }
        )
    dup = {"id": "x", "gpu": "a", "model": X2, "scale": 2, "input": "1x1"}
    with pytest.raises(ValueError, match="duplicate"):
        pr.parse_profiles({"profiles": [dup, dict(dup, id="y")]})


# ---- integration with RealESRGANNative ------------------------------------


class FakeOOM(Exception):
    pass


def _proc(monkeypatch, gpu, free_gib=15.2, source=None, explicit=None, tile=0):
    monkeypatch.setattr(n, "_is_cuda_oom", lambda exc: isinstance(exc, FakeOOM))
    monkeypatch.setattr(n, "_gpu_name", lambda: gpu)
    monkeypatch.setattr(n, "_free_vram_bytes", lambda: int(free_gib * GIB))
    p = n.RealESRGANNative.__new__(n.RealESRGANNative)
    p.scale = 2
    p.model_name = X2
    p.half = True
    p.actual_half = True
    p.tile_size = tile
    p._initial_tile_size = tile
    p.batch_size = 4
    p._auto_batch_size = 4
    p._explicit_batch_size = explicit
    p.settings_source = source or {"tile": "default", "batch": "auto"}
    p._upsampler = SimpleNamespace(scale=2, tile=tile, tile_size=tile)
    p.logger = logging.getLogger("test")
    p.tiled_calls = []

    def enhance(img, idx=None):
        p.tiled_calls.append(idx)
        return ("tiled", img)

    p._enhance_frame = enhance
    p._reset_execution_state()
    return p


def test_native_applies_4080_profile_over_auto_batch(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1920, 1080)
    assert p.tile_size == 512 and p._gpu_batch_size() == 1
    assert p.batch_source == "profile:rtx4080-x2plus-fp16-1080x1920"
    assert p.tile_reason == "profile:rtx4080-x2plus-fp16-1080x1920"
    assert p._upsampler.tile == 512


def test_native_applies_3090_profile(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 3090", free_gib=23.2)
    p._configure_batch_for_resolution(1920, 1080)
    assert p.tile_size == 0 and p._gpu_batch_size() == 2  # not auto 8


def test_unknown_gpu_keeps_auto_batch(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA L4", free_gib=21.5)
    p._configure_batch_for_resolution(1920, 1080)
    assert p.batch_source == "auto_vram" and p.tile_size == 0
    assert p._gpu_batch_size() == n.estimate_auto_batch(3840, 2160, X2, 21.5 * GIB)[0]


def test_other_resolution_keeps_auto_batch_on_4080(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1080, 1920)  # landscape
    assert p.batch_source == "auto_vram" and p.tile_size == 0


@pytest.mark.parametrize(
    "source,explicit,tile,expect_source",
    [
        ({"tile": "env", "batch": "auto"}, None, 0, "auto_vram"),  # TILE_SIZE=0 set
        ({"tile": "env", "batch": "env"}, 2, 0, "explicit"),  # staging today
        ({"tile": "default", "batch": "env"}, 2, 0, "explicit"),
        ({"tile": "option", "batch": "auto"}, None, 256, "auto_vram"),
    ],
)
def test_explicit_settings_win_over_profile(
    monkeypatch, source, explicit, tile, expect_source
):
    p = _proc(
        monkeypatch,
        "NVIDIA GeForce RTX 4080",
        source=source,
        explicit=explicit,
        tile=tile,
    )
    p._configure_batch_for_resolution(1920, 1080)
    assert p.batch_source == expect_source
    assert p.tile_size == tile
    assert getattr(p, "_perf_profile") is None


def test_oom_recovery_starts_from_3090_profile(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 3090", free_gib=23.2)
    p._configure_batch_for_resolution(1920, 1080)
    calls = []

    def fwd(upsampler, frames, scale, timing=None):
        calls.append(len(frames))
        if len(frames) > 1:
            raise FakeOOM("CUDA out of memory")
        return [("out", f) for f in frames]

    monkeypatch.setattr(n, "batch_forward", fwd)
    out = p._upscale_loaded(["a", "b"])
    assert out == [("out", "a"), ("out", "b")]
    assert calls == [2, 1, 1]
    assert [e["to_batch"] for e in p._oom_events] == [1]


def test_oom_recovery_from_tiled_4080_profile_halves_tile(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1920, 1080)
    p._step_down_after_oom(1)
    assert p.tile_size == 256 and p.oom_fallback is True


def test_profile_and_oom_state_do_not_leak_across_jobs(monkeypatch):
    n.begin_safe_batch_scope("job-1")
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 3090", free_gib=23.2)
    p._configure_batch_for_resolution(1920, 1080)
    p._step_down_after_oom(2)  # learn batch 1 in job-1
    assert n.safe_batch_snapshot()[0]["scope"] == "job-1"

    # next chunk of the same job starts from the learned cap
    p._reset_execution_state()
    p._configure_batch_for_resolution(1920, 1080)
    assert p._gpu_batch_size() == 1

    # a different job starts clean from the profile again
    assert n.begin_safe_batch_scope("job-2") is True
    assert n.safe_batch_snapshot() == []
    p._reset_execution_state()
    p._configure_batch_for_resolution(1920, 1080)
    assert p._gpu_batch_size() == 2 and p.oom_fallback is False

    # same process, different GPU-independent job on landscape input: no profile carried
    p._reset_execution_state()
    p._configure_batch_for_resolution(1080, 1920)
    assert p.batch_source == "auto_vram" and p._perf_profile is None


def test_reset_restores_initial_tile_after_profile(monkeypatch):
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1920, 1080)
    assert p.tile_size == 512
    p._reset_execution_state()
    assert p.tile_size == 0 and p._perf_profile is None


def test_broken_profiles_file_falls_back(monkeypatch, tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("profiles:\n  - {id: x}\n")
    monkeypatch.setenv("REAL_ESRGAN_PROFILES_FILE", str(f))
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1920, 1080)
    assert p.batch_source == "auto_vram"


def test_worker_scopes_safe_batches_per_job():
    from src.worker import processors as wp

    n.begin_safe_batch_scope("job-a")
    n.remember_safe_batch(n.safe_batch_key("g", X2, 1, 1), 1, 0)
    wp._begin_upscale_scope({"job_id": "job-a", "attempt_id": "a1"})
    assert len(n.safe_batch_snapshot()) == 1
    wp._begin_upscale_scope({"job_id": "job-b", "attempt_id": "b1"})
    assert n.safe_batch_snapshot() == [] and n.current_safe_batch_scope() == "job-b"


def test_learned_smaller_tile_caps_tiled_profile_next_chunk(monkeypatch):
    n.begin_safe_batch_scope("job-1")
    p = _proc(monkeypatch, "NVIDIA GeForce RTX 4080")
    p._configure_batch_for_resolution(1920, 1080)
    p._step_down_after_oom(1)  # tile 512 -> 256 learned
    p._reset_execution_state()
    p._configure_batch_for_resolution(1920, 1080)
    assert p.tile_size == 256 and p.tile_reason == "learned_oom"
