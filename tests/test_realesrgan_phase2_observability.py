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


def test_x2_weights_do_not_fallback_to_x4(monkeypatch):
    from src.infrastructure.processors.realesrgan.native import RealESRGANNative

    p = RealESRGANNative.__new__(RealESRGANNative)
    p.model_name = "RealESRGAN_x2plus"
    monkeypatch.setattr(Path, "exists", lambda path: "x4plus" in str(path))

    with pytest.raises(FileNotFoundError, match="refusing silent x4plus fallback"):
        p._find_model_weights()


def test_runtime_source_contains_observability_fields():
    source = Path("src/infrastructure/processors/realesrgan/native.py").read_text()
    for field in ("decode_s", "preprocess_s", "inference_s", "postprocess_s", "encode_s"):
        assert field in source
    assert "Real-ESRGAN runtime:" in source
    assert "CUDA OOM" in source


def test_legacy_loader_refuses_x2_to_x4_fallback():
    source = Path("realesrgan_batch_upscale.py").read_text()
    assert "refusing silent x4plus fallback" in source
