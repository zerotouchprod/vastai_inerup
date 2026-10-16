import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runpod_pilot_image_keeps_worker_code_outside_volume_mount():
    dockerfile_path = ROOT / "docker/Dockerfile.runpod-pilot"
    assert dockerfile_path.is_file(), "the dedicated Runpod pilot image must exist"
    dockerfile = dockerfile_path.read_text()

    assert "WORKDIR /opt/aividup/project" in dockerfile
    assert "PYTHONPATH=/opt/aividup/project" in dockerfile
    assert "/workspace/project" not in dockerfile
    assert "AIVIDUP_RIFE_CODE_DIR=/opt/aividup/project/RIFEv4.26_0921" in dockerfile


def test_rife_preflight_is_tagged_for_model_load_timing():
    start = (ROOT / "scripts/worker_start.sh").read_text()
    assert 'AIVIDUP_GPU_PREFLIGHT=1 "$PYTHON" /opt/aividup/cuda_runtime_preflight.py' in start


def test_runpod_pilot_image_requires_versioned_volume_and_pins_manifest():
    dockerfile_path = ROOT / "docker/Dockerfile.runpod-pilot"
    assert dockerfile_path.is_file(), "the dedicated Runpod pilot image must exist"
    dockerfile = dockerfile_path.read_text()

    assert "AIVIDUP_MODEL_VOLUME_ROOT=/workspace/models/rife-v4.26" in dockerfile
    assert "AIVIDUP_VERIFIED_MODEL_PARENT=/tmp" in dockerfile
    assert "AIVIDUP_MODEL_MANIFEST_REQUIRED=1" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "org.zerotouchprod.aividup.pipeline-version" in dockerfile
    assert "org.zerotouchprod.aividup.model-manifest-sha256" in dockerfile
    assert "pipeline_version" in dockerfile
    assert "manifest pipeline version differs from image" in dockerfile
    assert "AIVIDUP_PIPELINE_VERSION=${PIPELINE_VERSION}" in dockerfile
    assert "AIVIDUP_MODEL_MANIFEST_SHA256=${MODEL_MANIFEST_SHA256}" in dockerfile
    assert "MODE=interp" in dockerfile
    assert "AIVIDUP_MODEL_VOLUME_ROOT=/workspace/models/rife-v4.26" in dockerfile
    assert "/opt/aividup/model-manifest.expected.json" in dockerfile


def test_runpod_pilot_image_does_not_copy_model_weights_or_upscaler_assets():
    dockerfile_path = ROOT / "docker/Dockerfile.runpod-pilot"
    assert dockerfile_path.is_file(), "the dedicated Runpod pilot image must exist"
    dockerfile = dockerfile_path.read_text()

    assert "RIFEv4.26_0921/train_log/*.py" in dockerfile
    assert "flownet.pkl" not in dockerfile
    assert "realesrgan" not in dockerfile.lower()
    assert "propaint" not in dockerfile.lower()
    assert "sam2" not in dockerfile.lower()


def test_build_context_excludes_rife_weight_files():
    ignore_path = ROOT / "docker/Dockerfile.runpod-pilot.dockerignore"
    assert ignore_path.is_file(), "a Dockerfile-specific context ignore file is required"
    rules = ignore_path.read_text().splitlines()

    assert "!RIFEv4.26_0921/" in rules
    assert "RIFEv4.26_0921/train_log/*.pkl" in rules
    assert "!RIFEv4.26_0921/train_log/*.pkl" not in rules
    assert "!runpod/pilot/rife-v4.26/" in rules
    for extension in ("pkl", "pth", "ckpt", "safetensors", "onnx"):
        assert f"**/*.{extension}" in rules


def test_worker_ci_trigger_paths_cover_pilot_and_existing_assets():
    workflow = (ROOT / ".github/workflows/build-worker.yml").read_text()
    for path in (
        "contracts/worker-api-v1.json",
        "scripts/worker_image_acceptance.py",
        "scripts/build_worker.sh",
        "docker/Dockerfile.runpod-rife-esrgan-pilot",
        "scripts/build_runpod_rife_esrgan_pilot_worker.sh",
        "tests/unit/test_worker_task_mapping.py",
    ):
        assert workflow.count(f"'{path}'") >= 2
    assert "tests/unit/test_runpod_model_bundle.py" in workflow
    assert "tests/test_runpod_rife_timing.py" in workflow
    assert workflow.count("'scripts/export_runpod_rife_bundle.py'") >= 2


def test_pilot_build_only_on_pr_and_publication_is_manual_opt_in():
    build_script = ROOT / "scripts/build_runpod_pilot_worker.sh"
    workflow = ROOT / ".github/workflows/build-worker.yml"
    assert build_script.is_file(), "a local build-only script must be provided"
    assert os.access(build_script, os.X_OK), "the documented build script must be executable"
    assert workflow.is_file(), "the PR image build gate must be provided"
    script = build_script.read_text()
    assert "docker build" in script
    assert "docker push" not in script
    assert "ghcr.io" not in script
    workflow_text = workflow.read_text()
    assert "push: ${{ github.event_name == 'workflow_dispatch' && inputs.publish_runpod_pilot == true }}" in workflow_text
    assert "inputs.worker_sha == github.sha" in workflow_text
    assert "if: github.event_name != 'workflow_dispatch'" in workflow_text
    script_text = build_script.read_text()
    assert "git rev-parse HEAD" in script_text
    assert "git rev-parse --short HEAD" not in script_text
    exact_sha = "${{ github.event_name == 'workflow_dispatch' && inputs.worker_sha || github.event.pull_request.head.sha || github.sha }}"
    assert f"ref: {exact_sha}" in workflow_text
    assert f"GIT_SHA={exact_sha}" in workflow_text
    assert f"aividup-worker-runpod-rife-pilot:{exact_sha}" in workflow_text
