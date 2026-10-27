from pathlib import Path

import pytest


def test_resolution_aware_batch_caps_large_input(monkeypatch):
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    monkeypatch.setenv("REAL_ESRGAN_MAX_BATCH_PIXELS", str(12 * 1920 * 1080))
    p = RealESRGANNative.__new__(RealESRGANNative)
    p.batch_size = 12
    p._explicit_batch_size = None
    p._batch_configured_for_resolution = False
    p.logger = __import__("logging").getLogger("test")

    p._configure_batch_for_resolution(2160, 3840)

    assert p.batch_size == 3
    assert p._batch_configured_for_resolution is True


def test_auto_batch_is_the_actual_tile_zero_gpu_batch():
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    p = RealESRGANNative.__new__(RealESRGANNative)
    p.tile_size = 0
    p._explicit_batch_size = None
    p.batch_size = 12

    assert p._gpu_batch_size() == 12


def test_execution_state_resets_after_previous_job_tuning():
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    p = RealESRGANNative.__new__(RealESRGANNative)
    p.tile_size = 512
    p._initial_tile_size = 0
    p._explicit_batch_size = None
    p._auto_batch_size = 12
    p.batch_size = 1
    p._batch_configured_for_resolution = True
    p._oom_recovery_attempted = True
    p._upsampler = None

    p._reset_execution_state()

    assert p.tile_size == 0
    assert p.batch_size == 12
    assert p._batch_configured_for_resolution is False
    assert p._oom_recovery_attempted is False


def test_oom_recovery_is_bounded():
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    p = RealESRGANNative.__new__(RealESRGANNative)
    p.tile_size = 0
    p.batch_size = 12
    p._oom_recovery_attempted = False
    p._upsampler = None
    p.logger = __import__("logging").getLogger("test")

    p._recover_from_oom(12)
    assert p.tile_size == 512
    assert p.batch_size == 1
    with pytest.raises(RuntimeError, match="bounded recovery"):
        p._recover_from_oom(1)


def test_model_scale_mismatch_is_rejected():
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    with pytest.raises(ValueError, match="incompatible"):
        RealESRGANNative(scale=2, model_name="RealESRGAN_x4plus")


def test_x2_weights_do_not_fallback_to_x4(monkeypatch):
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    p = RealESRGANNative.__new__(RealESRGANNative)
    p.model_name = "RealESRGAN_x2plus"
    monkeypatch.setattr(Path, "exists", lambda path: "x4plus" in str(path))

    with pytest.raises(FileNotFoundError, match="refusing silent x4plus fallback"):
        p._find_model_weights()


def test_runtime_source_contains_observability_fields():
    source = Path("src/infrastructure/processors/realesrgan/native.py").read_text()
    for field in (
        "frame_read_s",
        "preprocess_s",
        "inference_s",
        "postprocess_s",
        "png_encode_s",
    ):
        assert field in source
    assert "Real-ESRGAN runtime:" in source
    assert "CUDA OOM" in source


def test_legacy_loader_refuses_x2_to_x4_fallback():
    source = Path("realesrgan_batch_upscale.py").read_text()
    assert "refusing silent x4plus fallback" in source
