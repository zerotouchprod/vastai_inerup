from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile.worker"
START = ROOT / "scripts" / "worker_start.sh"
IGNORE = ROOT / "docker" / "Dockerfile.worker.dockerignore"


def test_worker_image_contains_runtime_preflight_and_real_entrypoint():
    dockerfile = DOCKERFILE.read_text()
    ignore = IGNORE.read_text()

    assert "COPY scripts/cuda_runtime_preflight.py /opt/aividup/cuda_runtime_preflight.py" in dockerfile
    assert "scripts/cuda_runtime_preflight.py" in ignore
    assert 'ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/worker_start.sh"]' in dockerfile
    assert 'CMD ["sleep", "infinity"]' not in dockerfile


def test_worker_start_runs_pull_worker_and_selects_real_backend_probe():
    start = START.read_text()

    assert 'AIVIDUP_GPU_PROBE_BACKEND="${AIVIDUP_GPU_PROBE_BACKEND:-all}"' in start
    assert '"$PYTHON" -m src.worker' in start
    assert "--provider-instance-id" in start
    assert "--gpu-lease-id" in start
    assert "--boot-id" in start


def test_preflight_supports_all_configured_backends():
    preflight = (ROOT / "scripts" / "cuda_runtime_preflight.py").read_text()

    assert 'backend in {"all", "realesrgan"}' in preflight
    assert 'backend in {"all", "rife"}' in preflight
