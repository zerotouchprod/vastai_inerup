from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_combined_runpod_image_bakes_and_verifies_realesrgan_x2plus():
    dockerfile = ROOT / "docker/Dockerfile.runpod-rife-esrgan-pilot"
    assert dockerfile.is_file(), "a separate immutable RIFE+Real-ESRGAN pilot image must exist"
    text = dockerfile.read_text().lower()

    assert "aividup-worker-runpod-rife-esrgan-pilot" in text
    assert "pip install --no-deps basicsr realesrgan" in text
    assert "realesrgan_x2plus.pth" in text
    assert "realesrgan_x2plus_sha256" in text
    assert "sha256sum" in text
    assert "aividup_gpu_probe_backend=all" in text
    assert "/opt/realesrgan_models/realesrgan_x2plus.pth" in text or "/opt/realesrgan_models/RealESRGAN_x2plus.pth" in text
    assert "test -s /opt/realesrgan_models/realesrgan_x2plus.pth" in text


def test_combined_image_includes_basicsr_import_dependencies():
    dockerfile = (ROOT / "docker/Dockerfile.runpod-rife-esrgan-pilot").read_text()
    ignore = (ROOT / "docker/Dockerfile.runpod-rife-esrgan-pilot.dockerignore").read_text().splitlines()
    requirements = (ROOT / "requirements-worker.txt").read_text().lower()

    assert "COPY requirements-worker.txt" in dockerfile
    assert "!requirements-worker.txt" in ignore
    for package in ("addict", "future", "lmdb", "yapf", "tensorboard"):
        assert package in requirements


def test_combined_image_has_a_pipeline_manifest_and_local_build_script():
    manifest = ROOT / "runpod/pilot/rife-esrgan/manifest.json"
    assert manifest.is_file(), "combined image must pin its RIFE pipeline manifest"
    build_script = ROOT / "scripts/build_runpod_rife_esrgan_pilot_worker.sh"
    assert build_script.is_file(), "a local build-only helper must exist"
    script = build_script.read_text()
    assert "git rev-parse HEAD" in script
    assert "docker build" in script
    assert "docker push" not in script
    assert "Dockerfile.runpod-rife-esrgan-pilot" in script
    assert "aividup-worker-runpod-rife-esrgan-pilot" in script


def test_dual_model_image_publication_is_manual_and_digest_pinned():
    workflow = ROOT / ".github/workflows/build-worker.yml"
    text = workflow.read_text()
    assert "publish_dual_model_runpod_pilot" in text
    assert "default: false" in text
    assert "aividup-worker-runpod-rife-pilot" in text
    assert "Resolve immutable registry digest" in text
    assert "Verify anonymous registry digest" in text
    assert "docker-cpu-image-e2e.py" in text


def test_cli_task_params_include_scale_and_both_strategy():
    import argparse
    import importlib.util
    import sys

    path = ROOT / "scripts/runpod_pilot_test_control_plane.py"
    spec = importlib.util.spec_from_file_location("runpod_pilot_test_control_plane_dual", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args = argparse.Namespace(
        scale=2.0,
        interp_factor=2.0,
        target_fps=None,
        strategy="interp-then-upscale",
    )
    assert module.task_params_from_cli(args) == {
        "scale": 2.0,
        "interp_factor": 2.0,
        "target_fps": None,
        "strategy": "interp-then-upscale",
    }


def test_control_plane_task_serializes_both_model_settings(tmp_path, monkeypatch):
    import importlib.util
    import sys

    path = ROOT / "scripts/runpod_pilot_test_control_plane.py"
    spec = importlib.util.spec_from_file_location("runpod_pilot_test_control_plane_task", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    input_path = tmp_path / "source.mp4"
    input_path.write_bytes(b"source bytes are never processed by this test")
    monkeypatch.setattr(module, "probe_duration", lambda _path: 33.941333)

    plane = module.IsolatedControlPlane(
        token="cpu-test-token",
        input_path=input_path,
        mode="both",
        params={
            "scale": 2.0,
            "interp_factor": 2.0,
            "target_fps": None,
            "strategy": "interp-then-upscale",
        },
    )
    task = plane.build_task("attempt-dual")

    assert task["mode"] == "both"
    assert task["duration_seconds"] == 33.94
    assert task["params"] == {
        "scale": 2.0,
        "interp_factor": 2.0,
        "target_fps": None,
        "strategy": "interp-then-upscale",
    }


def test_dual_model_plane_unit_is_configurable_for_original_clip():
    unit = (ROOT / "ops/runpod-pilot/aividup-pilot-plane.service").read_text()
    assert "EnvironmentFile=/etc/aividup-runpod-pilot/plane.env" in unit
    assert "--input ${AIVIDUP_PILOT_INPUT}" in unit
    assert "--mode ${AIVIDUP_PILOT_MODE}" in unit
    assert "--scale ${AIVIDUP_PILOT_SCALE}" in unit
    assert "--interp-factor ${AIVIDUP_PILOT_INTERP_FACTOR}" in unit
    assert "--strategy ${AIVIDUP_PILOT_STRATEGY}" in unit
    assert "--evidence ${AIVIDUP_PILOT_EVIDENCE}" in unit
    assert "--output-dir ${AIVIDUP_PILOT_OUTPUT_DIR}" in unit


def test_controller_supervisor_accepts_only_configured_immutable_image_ref():
    script = (ROOT / "ops/runpod-pilot/controller-supervise.sh").read_text()
    assert "AIVIDUP_RUNPOD_IMAGE_REF" in script
    assert '--image "$IMAGE_REF"' in script
    assert '--disk-gb 40' in script
    assert "AIVIDUP_RUNPOD_POD_NAME" in script
    unit = (ROOT / "ops/runpod-pilot/aividup-runpod-pilot.service").read_text()
    assert "EnvironmentFile=-/etc/aividup-runpod-pilot/controller.env" in unit
