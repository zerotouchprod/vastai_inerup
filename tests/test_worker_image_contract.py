from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile.worker"
START = ROOT / "scripts" / "worker_start.sh"
IGNORE = ROOT / "docker" / "Dockerfile.worker.dockerignore"


def test_worker_image_contains_runtime_preflight_and_real_entrypoint():
    dockerfile = DOCKERFILE.read_text()
    ignore = IGNORE.read_text()

    assert (
        "COPY scripts/cuda_runtime_preflight.py /opt/aividup/cuda_runtime_preflight.py"
        in dockerfile
    )
    assert "scripts/cuda_runtime_preflight.py" in ignore
    assert (
        'ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/worker_start.sh"]'
        in dockerfile
    )
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


def test_blackwell_serverless_image_is_pinned_and_checksums_models():
    dockerfile = (ROOT / "docker" / "Dockerfile.aividup-serverless").read_text()

    assert (
        "FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04@"
        "sha256:59e0e4376a0f16d10b03d3a14344b80a866a1674cb4948cb318291387ac05010"
    ) in dockerfile
    assert (
        "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb" in dockerfile
    )
    assert (
        "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1" in dockerfile
    )
    assert "sha256sum -c" in dockerfile
    assert "TORCH_VERSION=2.9.1" in dockerfile
    assert "TORCHVISION_VERSION=0.24.1" in dockerfile
    assert "requirements-serverless-blackwell.txt" in dockerfile
