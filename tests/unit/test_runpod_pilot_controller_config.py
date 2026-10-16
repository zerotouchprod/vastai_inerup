"""Tests for safe injection of the isolated plane/tunnel into the one-shot Pod request."""

import json
from pathlib import Path

import pytest

from scripts import runpod_pilot_controller as controller_module
from scripts.runpod_pilot_controller import PilotController, PilotError, load_pod_env_file

IMAGE = (
    "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@"
    "sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
)
POD_ENV = {
    "AIVIDUP_API_URL": "http://127.0.0.1:18099/api/worker",
    "AIVIDUP_WORKER_TOKEN": "worker-token-never-log-this",
    "AIVIDUP_GPU_INSTANCE_ID": "pilot-instance-1",
    "AIVIDUP_GPU_LEASE_ID": "lease-1",
    "AIVIDUP_BOOT_ID": "boot-1",
    "AIVIDUP_TUNNEL_PRIVATE_KEY_B64": "private-key-base64-never-log-this",
}
POD_ARGS = json.dumps(
    {
        "entrypoint": ["/bin/bash", "-lc"],
        "cmd": ["install openssh-client; start restricted localhost tunnel; exec bootstrap"],
    }
)


def test_payload_includes_isolated_api_env_and_entrypoint_args(tmp_path):
    env_file = tmp_path / "pod.env"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in POD_ENV.items()) + "\n")
    env_file.chmod(0o600)
    args_file = tmp_path / "pod-args.json"
    args_file.write_text(POD_ARGS)

    payload_env = load_pod_env_file(env_file)
    controller = PilotController(
        api=None,
        state_path=tmp_path / "state.json",
        pod_name="pilot-one",
        image=IMAGE,
        deadline_seconds=1800,
        gpu_id="NVIDIA GeForce RTX 3090",
        data_centre="EU-CZ-1",
        env=payload_env,
        pod_args=args_file.read_text(),
    )

    payload = controller.build_payload()

    assert payload["image"] == IMAGE
    assert payload["gpu"] == {"id": "NVIDIA GeForce RTX 3090", "count": 1}
    assert payload["dataCenterIds"] == ["EU-CZ-1"]
    assert payload["env"]["AIVIDUP_API_URL"] == POD_ENV["AIVIDUP_API_URL"]
    assert payload["env"]["AIVIDUP_WORKER_TOKEN"] == POD_ENV["AIVIDUP_WORKER_TOKEN"]
    assert json.loads(payload["args"]) == json.loads(POD_ARGS)
    assert "mounts" not in payload


def test_pod_env_file_requires_owner_only_mode(tmp_path):
    env_file = tmp_path / "pod.env"
    env_file.write_text("AIVIDUP_API_URL=http://127.0.0.1:18099/api/worker\n")
    env_file.chmod(0o644)
    with pytest.raises(PilotError, match="0600"):
        load_pod_env_file(env_file)


def test_pod_env_file_rejects_duplicate_and_invalid_keys(tmp_path):
    duplicate = tmp_path / "duplicate.env"
    duplicate.write_text("AIVIDUP_API_URL=a\nAIVIDUP_API_URL=b\n")
    duplicate.chmod(0o600)
    with pytest.raises(PilotError, match="duplicate"):
        load_pod_env_file(duplicate)

    invalid = tmp_path / "invalid.env"
    invalid.write_text("RUNPOD_API_KEY=not-for-pod\n")
    invalid.chmod(0o600)
    with pytest.raises(PilotError, match="not permitted"):
        load_pod_env_file(invalid)


def test_pod_env_file_rejects_newline_injection(tmp_path):
    env_file = tmp_path / "injection.env"
    env_file.write_text("AIVIDUP_API_URL=http://127.0.0.1:18099/api/worker\nBAD KEY=x\n")
    env_file.chmod(0o600)
    with pytest.raises(PilotError):
        load_pod_env_file(env_file)


def test_pod_args_file_rejects_group_or_world_writable_command(tmp_path):
    args_file = tmp_path / "pod-args.json"
    args_file.write_text(POD_ARGS)
    args_file.chmod(0o666)
    with pytest.raises(PilotError, match="writable"):
        controller_module.load_pod_args_file(args_file)


def test_pod_args_http_probes_plane_before_bootstrap():
    args_file = Path(__file__).resolve().parents[2] / "ops" / "runpod-pilot" / "pod-args.json"
    args = json.loads(controller_module.load_pod_args_file(args_file))
    cmd = args["cmd"][0]
    assert "curl" in cmd
    assert "/api/worker/claim" in cmd
    assert "401" in cmd
    assert cmd.index("HTTP_STATUS") < cmd.index("runpod_checkpoint_bootstrap.py")


def test_pod_args_bootstrap_path_exists_inside_the_immutable_image():
    """Regression: the live pilot ran a host-only bootstrap path, so the container crash-looped.

    The path in the Pod args must be a destination the pilot Dockerfile actually copies.
    """
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "docker" / "Dockerfile.runpod-pilot").read_text()
    destinations = [
        line.split()[-1]
        for line in dockerfile.splitlines()
        if line.startswith("COPY scripts/runpod_checkpoint_bootstrap.py ")
    ]
    assert destinations, "the pilot image must copy the bootstrap script into the image"

    args = json.loads(
        controller_module.load_pod_args_file(root / "ops" / "runpod-pilot" / "pod-args.json")
    )
    cmd = args["cmd"][0]
    assert any(destination in cmd for destination in destinations)
    assert "/opt/aividup-runpod-pilot/" not in cmd


def test_pod_args_upload_cuda_rife_preflight_stdout_stderr_before_job_claim():
    args_file = Path(__file__).resolve().parents[2] / "ops" / "runpod-pilot" / "pod-args.json"
    args = json.loads(controller_module.load_pod_args_file(args_file))
    cmd = args["cmd"][0]
    assert "python3-log-wrapper" in cmd
    assert "/opt/aividup/cuda_runtime_preflight.py" in cmd
    assert '2> "$AIVIDUP_DIAGNOSTIC_STDERR"' in cmd
    assert 'AIVIDUP_DIAGNOSTIC_KEY="diagnostics-${AIVIDUP_BOOT_ID}-' in cmd
    assert "/api/worker/sink/$AIVIDUP_DIAGNOSTIC_KEY" in cmd
    assert cmd.index("HTTP_STATUS") < cmd.index("python3-log-wrapper")
    assert cmd.index("python3-log-wrapper") < cmd.index("runpod_checkpoint_bootstrap.py")


def test_dry_run_redacts_pod_secrets_and_never_posts(capsys, tmp_path):
    env_file = tmp_path / "pod.env"
    env_file.write_text("\n".join(f"{k}={v}" for k, v in POD_ENV.items()) + "\n")
    env_file.chmod(0o600)
    args_file = tmp_path / "pod-args.json"
    args_file.write_text(POD_ARGS)

    exit_code = controller_module.main(
        [
            "--dry-run",
            "--state-file", str(tmp_path / "state.json"),
            "--pod-name", "pilot-one",
            "--image", IMAGE,
            "--gpu", "NVIDIA GeForce RTX 3090",
            "--data-centre", "EU-CZ-1",
            "--pod-env-file", str(env_file),
            "--pod-args-file", str(args_file),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "worker-token-never-log-this" not in output
    assert "private-key-base64-never-log-this" not in output
    assert "[REDACTED]" in output
    payload = json.loads(output)
    assert payload["image"] == IMAGE
    assert payload["env"]["AIVIDUP_API_URL"] == POD_ENV["AIVIDUP_API_URL"]
    assert payload["env"]["AIVIDUP_WORKER_TOKEN"] == "[REDACTED]"
    assert json.loads(payload["args"]) == json.loads(POD_ARGS)
