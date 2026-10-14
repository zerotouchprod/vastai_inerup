import importlib.util
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE_PATH = ROOT / "src/infrastructure/processors/rife/native.py"


def load_rife_native():
    spec = importlib.util.spec_from_file_location("runpod_pilot_rife_native_code_test", NATIVE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RIFENative


def test_rife_code_resolves_from_image_path_outside_workspace(monkeypatch, tmp_path):
    code_dir = tmp_path / "opt" / "aividup" / "RIFEv4.26_0921"
    (code_dir / "model").mkdir(parents=True)
    (code_dir / "model" / "RIFE_HDv3.py").write_text("# test model code")
    monkeypatch.setenv("AIVIDUP_RIFE_CODE_DIR", str(code_dir))
    rife_native = load_rife_native()
    processor = rife_native.__new__(rife_native)
    processor.logger = logging.getLogger("test")

    assert processor._find_rife_repo_path() == code_dir
