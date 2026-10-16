from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "docker" / "Dockerfile.gpu-smoke"
RUNNER = ROOT / "tests" / "gpu_smoke" / "run.py"
DIGEST = "ghcr.io/zerotouchprod/aividup-worker@sha256:50de56d6768ec37751e5c446ac4e034d5d451ffe01f3e147340c79925c113879"


def test_smoke_runner_is_pinned_and_overrides_worker_entrypoint():
    text = DOCKERFILE.read_text()
    assert f"FROM {DIGEST}" in text
    assert (
        'ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/aividup/gpu_smoke.py"]'
        in text
    )
    assert "worker_start.sh" not in text


def test_smoke_runner_has_cpu_gate_preflight_and_single_result_contract():
    text = RUNNER.read_text()
    assert "/opt/aividup/cuda_runtime_preflight.py" in text
    assert "GPU_SMOKE_RESULT " in text
    assert text.count("GPU_SMOKE_RESULT ") == 1
    assert "GPU_SMOKE_CPU_ONLY" in text
    assert "return 1" in text
    assert "return 2" in text
    assert "raise SystemExit(main())" in text


def test_smoke_runner_writes_atomic_detail_and_short_summary_contract():
    text = RUNNER.read_text()
    assert "GPU_SMOKE_RESULT_PATH" in text
    assert "os.replace" in text
    assert '"cuda_pass"' in text
    assert '"rife_pass"' in text
    assert '"realesrgan_pass"' in text
    assert '"error_code"' in text
    assert 'INCONCLUSIVE' in text
