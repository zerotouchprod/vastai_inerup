import importlib.util
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE_PATH = ROOT / "src/infrastructure/processors/rife/native.py"


def load_rife_native():
    spec = importlib.util.spec_from_file_location("runpod_pilot_rife_native_test", NATIVE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RIFENative


def test_missing_explicit_model_directory_does_not_fall_back_to_legacy_weights(monkeypatch, tmp_path):
    legacy_dir = tmp_path / "RIFEv4.26_0921"
    legacy_dir.mkdir()
    (legacy_dir / "flownet.pkl").write_bytes(b"legacy weights")
    missing_volume = tmp_path / "verified-models" / "train_log"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AIVIDUP_RIFE_MODEL_DIR", str(missing_volume))
    rife_native = load_rife_native()

    with pytest.raises(FileNotFoundError, match="configured RIFE model directory"):
        rife_native(factor=2, logger=logging.getLogger("test"))


def test_rife_weights_are_resolved_from_explicit_network_volume(monkeypatch, tmp_path):
    weights_dir = tmp_path / "models" / "rife-v4.26" / "train_log"
    weights_dir.mkdir(parents=True)
    (weights_dir / "flownet.pkl").write_bytes(b"volume weights")
    monkeypatch.setenv("AIVIDUP_RIFE_MODEL_DIR", str(weights_dir))

    processor = load_rife_native()(factor=2, logger=logging.getLogger("test"))

    assert processor.model_path == weights_dir
