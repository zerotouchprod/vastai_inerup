import importlib.util
import logging
from pathlib import Path

from src.worker import __main__ as worker_main

ROOT = Path(__file__).resolve().parents[1]
NATIVE_PATH = ROOT / "src/infrastructure/processors/rife/native.py"


def load_rife_native():
    spec = importlib.util.spec_from_file_location("runpod_pilot_rife_timing_test", NATIVE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RIFENative


def test_model_load_duration_is_emitted_as_a_distinct_worker_metric(caplog):
    rife_native = load_rife_native()
    processor = rife_native.__new__(rife_native)
    processor.logger = logging.getLogger("runpod-pilot-timing-test")

    with caplog.at_level(logging.INFO, logger="runpod-pilot-timing-test"):
        elapsed = processor._record_model_load_duration(10.0, 12.25)

    assert elapsed == 2.25
    assert processor.model_load_seconds == 2.25
    assert "RIFE_MODEL_LOAD_SECONDS=2.250000" in caplog.text


def test_model_load_logs_preflight_phase(monkeypatch, caplog):
    rife_native = load_rife_native()
    processor = rife_native.__new__(rife_native)
    processor.logger = logging.getLogger("runpod-pilot-preflight-test")
    monkeypatch.setenv("AIVIDUP_GPU_PREFLIGHT", "1")

    with caplog.at_level(logging.INFO, logger="runpod-pilot-preflight-test"):
        processor._record_model_load_duration(3.0, 4.0)

    assert "RIFE_MODEL_LOAD_SECONDS=1.000000 phase=preflight" in caplog.text


def test_model_load_metric_is_unset_before_lazy_load(tmp_path):
    rife_native = load_rife_native()
    weights_dir = tmp_path / "train_log"
    weights_dir.mkdir()
    (weights_dir / "flownet.pkl").write_bytes(b"weights")

    processor = rife_native(factor=2, model_path=weights_dir)

    assert processor.model_load_seconds is None


def test_boot_to_claim_includes_entrypoint_preflight_time():
    started = worker_main._started_at_from_uptime(
        now_monotonic=120.0,
        entrypoint_uptime=500.0,
        current_uptime=503.25,
    )
    assert started == 116.75


def test_boot_to_claim_does_not_move_start_into_the_future():
    assert worker_main._started_at_from_uptime(120.0, 500.0, 499.0) == 120.0
