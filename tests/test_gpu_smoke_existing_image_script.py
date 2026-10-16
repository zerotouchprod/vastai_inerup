from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_gpu_smoke_existing_image.sh"


def test_existing_image_smoke_script_uses_runtime_paths_and_runner():
    text = SCRIPT.read_text()
    assert 'PROJECT_ROOT="${PROJECT_ROOT:-/workspace/project}"' in text
    assert 'GPU_SMOKE_RESULT_PATH' in text
    assert 'GPU_SMOKE_DIAGNOSTIC_PATH' in text
    assert 'tests/gpu_smoke/run.py' in text
    assert 'exec "$PYTHON"' in text
