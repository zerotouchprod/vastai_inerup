#!/usr/bin/env python3
"""Run the exact immutable pilot image and pod-args on CPU through a test SSH tunnel.

This script never contacts RunPod. It creates a local synthetic job, a temporary
restricted SSH account, and a loopback-only control plane, then expects the
published GPU image to stop at its real CUDA preflight on a CPU-only runner.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
POD_ARGS_PATH = REPO_ROOT / "ops" / "runpod-pilot" / "pod-args.json"
DEFAULT_IMAGE = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
SSH_HOST_ALIAS = "195.234.126.233"
SSH_USER = "aividup-pilot-tunnel"
SSH_FORWARD_TARGET = "127.0.0.1:8099"
PLANE_HOST = "127.0.0.1"
PLANE_PORT = 8099
ADVERTISED_URL = "http://127.0.0.1:18099/api/worker"
EXPECTED_STAGES = [
    "tunnel_ready",
    "http_probe_pass",
    "bootstrap_started",
    "checkpoint_verified",
    "worker_started",
    "cuda_preflight",
]


class E2EFailure(RuntimeError):
    """The CPU image smoke did not meet its evidence contract."""


def load_plane_module():
    path = REPO_ROOT / "scripts" / "runpod_pilot_test_control_plane.py"
    spec = importlib.util.spec_from_file_location("runpod_pilot_test_control_plane", path)
    if spec is None or spec.loader is None:
        raise E2EFailure("cannot load the isolated control-plane module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_docker_argv(pod_args: dict[str, Any], image: str, env_file: Path) -> list[str]:
    """Translate the pod's entrypoint/cmd verbatim to `docker run` arguments."""
    entrypoint = pod_args.get("entrypoint")
    command = pod_args.get("cmd")
    if not isinstance(entrypoint, list) or not entrypoint or not all(isinstance(x, str) for x in entrypoint):
        raise E2EFailure("pod-args entrypoint must be a non-empty string array")
    if not isinstance(command, list) or len(command) != 1 or not isinstance(command[0], str):
        raise E2EFailure("pod-args cmd must contain exactly one shell command")
    return [
        "docker", "run", "--rm", "--pull=never",
        "--name", f"aividup-pilot-cpu-e2e-{uuid.uuid4().hex[:12]}",
        "--add-host", f"{SSH_HOST_ALIAS}:host-gateway",
        "--env-file", str(env_file),
        "--entrypoint", entrypoint[0],
        image,
        *entrypoint[1:],
        *command,
    ]


def run_checked(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise E2EFailure(f"command failed ({result.returncode}): {command[0]} {detail}")
    return result


def ensure_sshd_privsep_dir() -> None:
    """Create OpenSSH's runtime directory on minimal hosted runners."""
    run_checked(["sudo", "-n", "install", "-d", "-o", "root", "-g", "root", "-m", "0755", "/run/sshd"])


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
        if not content.endswith("\n"):
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(path, 0o600)


def prepare_temporary_sshd(secret_dir: Path) -> tuple[Path, Path, Path, str, str]:
    """Create a no-shell key restricted to the local plane listener only."""
    if shutil.which("ssh-keygen") is None or not Path("/usr/sbin/sshd").is_file():
        raise E2EFailure("openssh-client and openssh-server are required on the CI runner")
    user_check = subprocess.run(["id", "-u", SSH_USER], capture_output=True, text=True, check=False)
    if user_check.returncode == 0:
        raise E2EFailure(f"temporary SSH account already exists: {SSH_USER}")

    client_key = secret_dir / "client_ed25519"
    host_key = secret_dir / "host_ed25519"
    run_checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(client_key)])
    run_checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)])
    os.chmod(client_key, 0o600)
    os.chmod(host_key, 0o600)

    public_key = client_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    host_public = run_checked(["ssh-keygen", "-y", "-f", str(host_key)]).stdout.strip().split()
    if len(host_public) < 2:
        raise E2EFailure("could not derive temporary SSH host public key")
    pinned_host_key = f"{SSH_HOST_ALIAS} {host_public[0]} {host_public[1]}"

    home = secret_dir / "ssh-home"
    home.mkdir(mode=0o700)
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700)
    authorized_keys = ssh_dir / "authorized_keys"
    key_entry = f'no-agent-forwarding,no-X11-forwarding,no-pty,permitopen="{SSH_FORWARD_TARGET}" {public_key}'
    write_private(authorized_keys, key_entry)
    run_checked(["sudo", "-n", "useradd", "--system", "--user-group", "--no-create-home", "--home-dir", str(home), "--shell", "/usr/sbin/nologin", SSH_USER])
    try:
        config = secret_dir / "sshd_config"
        config_text = "\n".join(
            [
                "Port 22",
                "ListenAddress 0.0.0.0",
                f"HostKey {host_key}",
                f"PidFile {secret_dir / 'sshd.pid'}",
                f"AuthorizedKeysFile {authorized_keys}",
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "PubkeyAuthentication yes",
                "PermitRootLogin no",
                f"AllowUsers {SSH_USER}",
                "AllowTcpForwarding local",
                f"PermitOpen {SSH_FORWARD_TARGET}",
                "GatewayPorts no",
                "X11Forwarding no",
                "AllowAgentForwarding no",
                "PermitTunnel no",
                "PermitTTY no",
                "UsePAM no",
                "StrictModes no",
                "LogLevel VERBOSE",
                f"Match User {SSH_USER}",
                "    ForceCommand /usr/sbin/nologin",
                "    PermitTTY no",
                "    AllowTcpForwarding local",
                f"    PermitOpen {SSH_FORWARD_TARGET}",
                "",
            ]
        )
        write_private(config, config_text)
        ensure_sshd_privsep_dir()
        run_checked(["sudo", "-n", "/usr/sbin/sshd", "-t", "-f", str(config)])
        return client_key, host_key, config, pinned_host_key, str(home)
    except Exception:
        subprocess.run(["sudo", "-n", "userdel", "--remove", SSH_USER], capture_output=True, text=True, check=False)
        raise


def wait_for_port(host: str, port: int, process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise E2EFailure(f"temporary sshd exited early; exit={process.returncode}")
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise E2EFailure(f"temporary sshd did not listen on {host}:{port} within {timeout:g}s")


def verify_evidence(evidence: dict[str, Any], output_dir: Path, container_exit: int) -> dict[str, Any]:
    if container_exit == 0:
        raise E2EFailure("container unexpectedly succeeded on a CPU-only runner; expected the real CUDA preflight to fail")
    stages = [item.get("stage") for item in evidence.get("diagnostic_stages", [])]
    if stages != EXPECTED_STAGES:
        raise E2EFailure(f"stage timeline mismatch: expected={EXPECTED_STAGES}; got={stages}")
    if evidence.get("claims_served") != 0 or evidence.get("claims"):
        raise E2EFailure("CPU image unexpectedly claimed the isolated job before CUDA preflight")
    if evidence.get("completed") or evidence.get("failures"):
        raise E2EFailure("isolated plane recorded worker activity before CUDA preflight")

    outputs = evidence.get("outputs", [])
    preflight = [item for item in outputs if "cuda-preflight" in str(item.get("key", ""))]
    if len(preflight) != 1:
        raise E2EFailure(f"expected one persisted CUDA preflight log; found {len(preflight)}")
    preflight_path = Path(preflight[0].get("file", ""))
    if not preflight_path.is_file():
        raise E2EFailure("persisted CUDA/RIFE preflight log file is missing")
    preflight_bytes = preflight_path.read_bytes()
    if b"CUDA_RUNTIME_PREFLIGHT_FAIL" not in preflight_bytes:
        raise E2EFailure("CPU image did not report the expected CUDA preflight failure")

    bootstrap_logs = [item for item in outputs if "-bootstrap-" in str(item.get("key", ""))]
    if not bootstrap_logs:
        raise E2EFailure("bootstrap stdout/stderr was not persisted by the container cleanup path")

    verified_logs = []
    for item in outputs:
        if not str(item.get("key", "")).startswith("diagnostics-"):
            continue
        path = Path(item.get("file", ""))
        if not path.is_file():
            raise E2EFailure(f"diagnostic file missing: {item.get('key')}")
        content = path.read_bytes()
        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != item.get("sha256"):
            raise E2EFailure(f"diagnostic hash mismatch: {item.get('key')}")
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise E2EFailure(f"diagnostic permissions are not 0600: {item.get('key')}")
        verified_logs.append({"key": item["key"], "bytes": len(content), "sha256": actual_sha})

    return {
        "container_exit_code": container_exit,
        "expected_result": "CUDA preflight failed on CPU; no worker claim",
        "diagnostic_stages": stages,
        "claims_served": evidence.get("claims_served"),
        "diagnostic_outputs": verified_logs,
        "preflight_failure_excerpt": preflight_bytes.decode("utf-8", "replace")[:1200],
    }


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--container-timeout", type=int, default=900)
    args = parser.parse_args(argv)
    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(artifact_dir, 0o700)
    evidence_path = artifact_dir / "plane-evidence.json"
    output_dir = artifact_dir / "plane-output"
    summary: dict[str, Any] = {
        "image": args.image,
        "runpod_api_called": False,
        "gpu_requested": False,
        "network_volume_requested": False,
    }
    plane = None
    sshd_process: subprocess.Popen[str] | None = None
    sshd_pid_file: Path | None = None
    container_name = f"aividup-pilot-cpu-e2e-{uuid.uuid4().hex[:12]}"
    user_created = False
    token = secrets.token_urlsafe(32)

    try:
        if args.image != DEFAULT_IMAGE:
            raise E2EFailure("image override is forbidden; use the pinned immutable digest")
        if shutil.which("docker") is None:
            raise E2EFailure("Docker CLI is unavailable")
        image_check = subprocess.run(["docker", "image", "inspect", args.image], capture_output=True, text=True, check=False)
        if image_check.returncode != 0:
            raise E2EFailure("pinned image is not present locally; CI must pull it by digest before this script")

        plane_module = load_plane_module()
        with tempfile.TemporaryDirectory(prefix="aividup-pilot-cpu-secrets-") as secret_temp:
            secret_dir = Path(secret_temp)
            input_path = plane_module.make_synthetic_input(secret_dir / "input.mp4", seconds=2.0)
            plane = plane_module.IsolatedControlPlane(
                token=token,
                input_path=input_path,
                host=PLANE_HOST,
                port=PLANE_PORT,
                evidence_path=evidence_path,
                output_dir=output_dir,
                advertised_base_url=ADVERTISED_URL,
                mode="interp",
                params={"interp_factor": 2.0},
            ).start()

            client_key, _, sshd_config, pinned_host_key, _home = prepare_temporary_sshd(secret_dir)
            user_created = True
            sshd_pid_file = secret_dir / "sshd.pid"
            sshd_log_path = secret_dir / "sshd.log"
            sshd_log = sshd_log_path.open("w", encoding="utf-8")
            sshd_process = subprocess.Popen(
                ["sudo", "-n", "/usr/sbin/sshd", "-D", "-e", "-f", str(sshd_config)],
                stdout=sshd_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            wait_for_port("127.0.0.1", 22, sshd_process)

            env_file = secret_dir / "pod.env"
            env = {
                "AIVIDUP_API_URL": ADVERTISED_URL,
                "AIVIDUP_WORKER_TOKEN": token,
                "AIVIDUP_GPU_INSTANCE_ID": "cpu-image-e2e-instance",
                "AIVIDUP_GPU_LEASE_ID": str(uuid.uuid4()),
                "AIVIDUP_BOOT_ID": str(uuid.uuid4()),
                "AIVIDUP_TUNNEL_PRIVATE_KEY_B64": base64.b64encode(client_key.read_bytes()).decode("ascii"),
                "AIVIDUP_TUNNEL_HOST_KEY": pinned_host_key,
            }
            write_private(env_file, "".join(f"{key}={value}\n" for key, value in env.items()))

            pod_args = json.loads(POD_ARGS_PATH.read_text(encoding="utf-8"))
            docker_argv = build_docker_argv(pod_args, args.image, env_file)
            docker_argv[docker_argv.index("--name") + 1] = container_name
            summary["pod_args_sha256"] = hashlib.sha256(POD_ARGS_PATH.read_bytes()).hexdigest()
            summary["entrypoint"] = pod_args["entrypoint"]
            summary["exact_pod_args_command_used"] = True

            try:
                result = subprocess.run(
                    docker_argv,
                    capture_output=True,
                    text=True,
                    timeout=args.container_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True, check=False)
                stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                (artifact_dir / "container.stdout.txt").write_text(stdout.replace(token, "[REDACTED]"), encoding="utf-8")
                (artifact_dir / "container.stderr.txt").write_text(stderr.replace(token, "[REDACTED]"), encoding="utf-8")
                raise E2EFailure(f"container exceeded {args.container_timeout}s timeout") from exc

            safe_stdout = result.stdout.replace(token, "[REDACTED]")
            safe_stderr = result.stderr.replace(token, "[REDACTED]")
            (artifact_dir / "container.stdout.txt").write_text(safe_stdout, encoding="utf-8")
            (artifact_dir / "container.stderr.txt").write_text(safe_stderr, encoding="utf-8")
            summary.update({"container_exit_code": result.returncode, "container_stdout_bytes": len(safe_stdout.encode()), "container_stderr_bytes": len(safe_stderr.encode())})

            evidence = plane.evidence()
            save_json(evidence_path, evidence)
            summary.update(verify_evidence(evidence, output_dir, result.returncode))
            save_json(artifact_dir / "summary.json", summary)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        if plane is not None:
            try:
                evidence = plane.evidence()
                save_json(evidence_path, evidence)
                summary["diagnostic_stages"] = [item.get("stage") for item in evidence.get("diagnostic_stages", [])]
                summary["claims_served"] = evidence.get("claims_served")
            except Exception as evidence_error:
                summary["evidence_error"] = f"{type(evidence_error).__name__}: {evidence_error}"
        save_json(artifact_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if sshd_process is not None:
            try:
                if sshd_process.poll() is None:
                    if sshd_pid_file is not None and sshd_pid_file.is_file():
                        subprocess.run(["sudo", "-n", "kill", sshd_pid_file.read_text().strip()], capture_output=True, text=True, check=False)
                    else:
                        os.killpg(sshd_process.pid, signal.SIGTERM)
                sshd_process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(sshd_process.pid, signal.SIGKILL)
                except OSError:
                    pass
        if plane is not None:
            plane.stop()
        if user_created:
            subprocess.run(["sudo", "-n", "userdel", "--remove", SSH_USER], capture_output=True, text=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
