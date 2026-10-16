"""Contract tests for the opt-in immutable-image CPU E2E runner."""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "ops" / "runpod-pilot" / "docker-cpu-image-e2e.py"
POD_ARGS_PATH = REPO_ROOT / "ops" / "runpod-pilot" / "pod-args.json"


def load_runner():
    assert RUNNER_PATH.is_file(), "CPU image E2E runner is missing"
    spec = importlib.util.spec_from_file_location("runpod_cpu_image_e2e", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sidecar_ssh_materials_restrict_forwarding_to_loopback_plane(tmp_path):
    runner = load_runner()
    client_dir = tmp_path / "client"
    sidecar_dir = tmp_path / "sidecar"
    client_dir.mkdir()
    sidecar_dir.mkdir()

    client_key, pinned_host_key, host_key_fingerprint, client_key_fingerprint, config = runner.prepare_tunnel_materials(client_dir, sidecar_dir)

    assert client_key.is_file()
    assert pinned_host_key.startswith("195.234.126.233 ssh-ed25519 ")
    assert host_key_fingerprint.startswith("SHA256:")
    assert client_key_fingerprint.startswith("SHA256:")
    assert "PermitOpen 127.0.0.1:8099" in config.read_text()
    assert f"AuthorizedKeysFile /home/{runner.SSH_USER}/.ssh/authorized_keys" in config.read_text()
    assert "StrictModes yes" in config.read_text()
    assert "HostKey /run/ssh_host_ed25519" in config.read_text()
    authorized = (sidecar_dir / "authorized_keys").read_text()
    assert 'permitopen="127.0.0.1:8099"' in authorized
    assert "no-pty" in authorized and "no-agent-forwarding" in authorized
    allowed_fp = runner.run_checked(["ssh-keygen", "-lf", str(sidecar_dir / "authorized_keys")]).stdout.split()[1]
    assert client_key_fingerprint == allowed_fp


def test_sidecar_command_has_valid_shell_and_runs_plane_with_sshd(tmp_path):
    runner = load_runner()
    command = runner.build_sidecar_command(tmp_path / "sidecar", tmp_path / "artifacts")
    result = subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "openssh-server" in command
    assert "policy-rc.d" in command
    assert "install -o root -g root -m 0600" in command
    assert f"install -d -o {runner.SSH_USER} -g {runner.SSH_USER}" in command
    assert f"install -o {runner.SSH_USER} -g {runner.SSH_USER} -m 0600" in command
    assert 'usermod --password "$PASSWORD_HASH"' in command
    assert "sshd -D -e" in command
    assert "--host 127.0.0.1 --port 8099" in command


def test_sidecar_is_assigned_the_worker_literal_ssh_ip(tmp_path):
    runner = load_runner()
    image = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
    argv = runner.build_sidecar_argv(
        image,
        "pilot-sidecar",
        "pilot-e2e-net",
        tmp_path / "sidecar",
        tmp_path / "artifacts",
    )

    assert argv[argv.index("--network") + 1] == "pilot-e2e-net"
    assert argv[argv.index("--ip") + 1] == runner.SSH_HOST_ALIAS


def test_docker_command_uses_exact_pod_args_without_gpu_or_host_mounts(tmp_path):
    runner = load_runner()
    pod_args = json.loads(POD_ARGS_PATH.read_text())
    env_file = tmp_path / "pod.env"

    image = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
    argv = runner.build_docker_argv(
        pod_args,
        image,
        env_file,
        network_name="pilot-e2e-net",
    )

    image_index = argv.index(image)
    assert argv[image_index + 1 :] == pod_args["entrypoint"][1:] + pod_args["cmd"]
    assert argv[argv.index("--entrypoint") + 1] == pod_args["entrypoint"][0]
    assert argv[argv.index("--env-file") + 1] == str(env_file)
    assert argv[argv.index("--network") + 1] == "pilot-e2e-net"
    assert "--add-host" not in argv
    assert ipaddress.ip_address("195.234.126.233") in ipaddress.ip_network(runner.SIDECAR_SUBNET)
    assert "--gpus" not in argv
    assert "-v" not in argv and "--volume" not in argv


def test_cpu_runner_accepts_only_pinned_pilot_digest_or_local_image_id():
    runner = load_runner()
    dual_digest = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:" + "a" * 64

    assert runner.is_allowed_image_ref(dual_digest)
    assert runner.is_allowed_image_ref("sha256:" + "b" * 64)
    assert not runner.is_allowed_image_ref("ghcr.io/other/image@sha256:" + "a" * 64)
    assert not runner.is_allowed_image_ref("ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot:latest")


def test_sidecar_command_can_serialize_both_model_mode_parameters(tmp_path):
    runner = load_runner()
    command = runner.build_sidecar_command(
        tmp_path / "sidecar",
        tmp_path / "artifacts",
        mode="both",
        scale=2.0,
        interp_factor=2.0,
        strategy="interp-then-upscale",
    )

    assert "--mode both" in command
    assert "--scale 2.0" in command
    assert "--interp-factor 2.0" in command
    assert "--strategy interp-then-upscale" in command


def test_cpu_runner_requires_known_source_title_and_revision_for_local_image():
    runner = load_runner()
    trusted = {
        "org.opencontainers.image.source": "https://github.com/zerotouchprod/vastai_inerup",
        "org.opencontainers.image.title": "aividup-worker-runpod-rife-esrgan-pilot",
        "org.opencontainers.image.revision": "a" * 40,
        "org.zerotouchprod.aividup.pipeline-version": "aividup-rife-interp-v1",
        "org.zerotouchprod.aividup.realesrgan-x2plus-sha256": "b" * 64,
    }
    assert runner.is_trusted_pilot_image_labels(trusted, require_dual_model=True)
    assert runner.is_trusted_pilot_image_labels({**trusted, "org.opencontainers.image.title": "aividup-worker-runpod-rife-pilot"})
    assert not runner.is_trusted_pilot_image_labels({**trusted, "org.opencontainers.image.title": "aividup-worker-runpod-rife-pilot"}, require_dual_model=True)
    assert not runner.is_trusted_pilot_image_labels({**trusted, "org.opencontainers.image.source": "https://example.invalid/foreign"})
    assert not runner.is_trusted_pilot_image_labels({**trusted, "org.opencontainers.image.revision": "latest"})
    assert not runner.is_trusted_pilot_image_labels({**trusted, "org.zerotouchprod.aividup.realesrgan-x2plus-sha256": "bad"}, require_dual_model=True)
