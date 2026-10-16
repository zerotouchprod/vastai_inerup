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
import shlex
import shutil
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
SIDECAR_SUBNET = "195.234.126.232/29"
SIDECAR_GATEWAY = "195.234.126.234"
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


def build_docker_argv(
    pod_args: dict[str, Any],
    image: str,
    env_file: Path,
    *,
    network_name: str,
) -> list[str]:
    """Translate the pod entrypoint/cmd verbatim onto the isolated test Docker network."""
    entrypoint = pod_args.get("entrypoint")
    command = pod_args.get("cmd")
    if not isinstance(entrypoint, list) or not entrypoint or not all(isinstance(x, str) for x in entrypoint):
        raise E2EFailure("pod-args entrypoint must be a non-empty string array")
    if not isinstance(command, list) or len(command) != 1 or not isinstance(command[0], str):
        raise E2EFailure("pod-args cmd must contain exactly one shell command")
    return [
        "docker", "run", "--rm", "--pull=never",
        "--name", f"aividup-pilot-cpu-e2e-{uuid.uuid4().hex[:12]}",
        "--network", network_name,
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


def prepare_tunnel_materials(client_dir: Path, sidecar_dir: Path) -> tuple[Path, str, str, Path]:
    """Create pinned SSH material for a network-isolated test sidecar."""
    if shutil.which("ssh-keygen") is None:
        raise E2EFailure("openssh-client is required on the CI runner")
    client_key = client_dir / "client_ed25519"
    host_key = sidecar_dir / "host_ed25519"
    run_checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(client_key)])
    run_checked(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)])
    os.chmod(client_key, 0o600)
    os.chmod(host_key, 0o600)

    public_key = client_key.with_suffix(".pub").read_text(encoding="utf-8").strip()
    host_public = run_checked(["ssh-keygen", "-y", "-f", str(host_key)]).stdout.strip().split()
    if len(host_public) < 2:
        raise E2EFailure("could not derive temporary SSH host public key")
    pinned_host_key = f"{SSH_HOST_ALIAS} {host_public[0]} {host_public[1]}"
    fingerprint = run_checked(["ssh-keygen", "-lf", str(host_key)]).stdout.split()[1]
    key_entry = f'no-agent-forwarding,no-X11-forwarding,no-pty,permitopen="{SSH_FORWARD_TARGET}" {public_key}'
    write_private(sidecar_dir / "authorized_keys", key_entry)

    config = sidecar_dir / "sshd_config"
    config_text = "\n".join(
        [
            "Port 22",
            "ListenAddress 0.0.0.0",
            "HostKey /run/ssh_host_ed25519",
            "PidFile /run/sshd.pid",
            f"AuthorizedKeysFile {sidecar_dir / 'authorized_keys'}",
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
    return client_key, pinned_host_key, fingerprint, config


def build_sidecar_command(sidecar_dir: Path, artifact_dir: Path) -> str:
    """Start a restricted SSHD and the one-job plane in the same container namespace."""
    quote = shlex.quote
    plane_script = sidecar_dir / "runpod_pilot_test_control_plane.py"
    token_file = sidecar_dir / "plane.token"
    input_path = sidecar_dir / "input.mp4"
    evidence_path = artifact_dir / "plane-evidence.json"
    output_dir = artifact_dir / "plane-output"
    config = sidecar_dir / "sshd_config"
    lines = [
        "set -euo pipefail",
        "export DEBIAN_FRONTEND=noninteractive",
        "POLICY_CREATED=0",
        "if [ ! -e /usr/sbin/policy-rc.d ]; then printf '%s\\n' '#!/bin/sh' 'exit 101' > /usr/sbin/policy-rc.d; chmod 0755 /usr/sbin/policy-rc.d; POLICY_CREATED=1; fi",
        "apt-get update -qq",
        "apt-get install -y -qq --no-install-recommends openssh-server",
        "if [ \"$POLICY_CREATED\" -eq 1 ]; then rm -f /usr/sbin/policy-rc.d; fi",
        "rm -rf /var/lib/apt/lists/*",
        "install -d -m 0755 /run/sshd",
        f"install -o root -g root -m 0600 {quote(str(sidecar_dir / 'host_ed25519'))} /run/ssh_host_ed25519",
        "ssh-keygen -lf /run/ssh_host_ed25519",
        f"useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin {SSH_USER}",
        "PASSWORD_HASH=$(python3 -c 'import crypt,secrets; print(crypt.crypt(secrets.token_urlsafe(32), crypt.mksalt(crypt.METHOD_SHA512)))')",
        f"usermod --password \"$PASSWORD_HASH\" {SSH_USER}",
        "unset PASSWORD_HASH",
        f"/usr/sbin/sshd -t -f {quote(str(config))}",
        f"/usr/sbin/sshd -D -e -f {quote(str(config))} &",
        "SSHD_PID=$!",
        (
            f"python3 {quote(str(plane_script))} --token-file {quote(str(token_file))} "
            f"--input {quote(str(input_path))} --host 127.0.0.1 --port {PLANE_PORT} "
            f"--advertised-base-url {quote(ADVERTISED_URL)} --evidence {quote(str(evidence_path))} "
            f"--output-dir {quote(str(output_dir))} --mode interp --interp-factor 2.0 &"
        ),
        "PLANE_PID=$!",
        "shutdown() { status=$?; trap - EXIT INT TERM; kill \"$PLANE_PID\" \"$SSHD_PID\" 2>/dev/null || true; wait \"$PLANE_PID\" 2>/dev/null || true; wait \"$SSHD_PID\" 2>/dev/null || true; exit \"$status\"; }",
        "trap shutdown EXIT INT TERM",
        "wait -n \"$SSHD_PID\" \"$PLANE_PID\"",
    ]
    return "\n".join(lines)


def build_sidecar_argv(
    image: str,
    container_name: str,
    network_name: str,
    sidecar_dir: Path,
    artifact_dir: Path,
) -> list[str]:
    command = build_sidecar_command(sidecar_dir, artifact_dir)
    return [
        "docker", "run", "--detach", "--name", container_name,
        "--network", network_name, "--ip", SSH_HOST_ALIAS,
        "--mount", f"type=bind,source={sidecar_dir},target={sidecar_dir},readonly",
        "--mount", f"type=bind,source={artifact_dir},target={artifact_dir}",
        "--entrypoint", "/usr/bin/tini", image, "--", "/bin/bash", "-lc", command,
    ]


def get_container_ip(container_name: str, network_name: str) -> str:
    info = json.loads(run_checked(["docker", "inspect", container_name]).stdout)[0]
    try:
        ip = info["NetworkSettings"]["Networks"][network_name]["IPAddress"]
    except (KeyError, TypeError) as exc:
        raise E2EFailure(f"cannot find sidecar address on Docker network {network_name}") from exc
    if not ip:
        raise E2EFailure(f"sidecar has no IPv4 address on Docker network {network_name}")
    return str(ip)


def _docker_logs(container_name: str) -> tuple[str, str]:
    result = subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, check=False)
    return result.stdout or "", result.stderr or ""


def wait_for_sidecar_ready(container_name: str, timeout: float = 90.0) -> None:
    """Wait for both SSHD and the unauthenticated plane probe inside the sidecar."""
    deadline = time.monotonic() + timeout
    ssh_probe = "import socket; s=socket.create_connection(('127.0.0.1',22),timeout=1); s.close()"
    plane_probe = (
        "status=$(/usr/bin/curl --silent --show-error --max-time 2 -o /dev/null "
        "-w '%{http_code}' -X POST -H 'Content-Type: application/json' --data '{}' "
        f"http://127.0.0.1:{PLANE_PORT}/api/worker/claim); test \"$status\" = 401"
    )
    while time.monotonic() < deadline:
        state = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if state.returncode != 0 or state.stdout.strip() != "true":
            out, err = _docker_logs(container_name)
            raise E2EFailure(f"SSH/plane sidecar exited before readiness: {out[-1000:]} {err[-1000:]}")
        ssh = subprocess.run(
            ["docker", "exec", container_name, "python3", "-c", ssh_probe],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        plane = subprocess.run(
            ["docker", "exec", container_name, "/bin/bash", "-lc", plane_probe],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if ssh.returncode == 0 and plane.returncode == 0:
            return
        time.sleep(0.75)
    out, err = _docker_logs(container_name)
    raise E2EFailure(f"SSH/plane sidecar not ready within {timeout:g}s: {out[-1000:]} {err[-1000:]}")


def capture_and_remove_sidecar(container_name: str, artifact_dir: Path, token: str) -> None:
    stdout, stderr = _docker_logs(container_name)
    (artifact_dir / "sidecar.stdout.txt").write_text(stdout.replace(token, "[REDACTED]"), encoding="utf-8")
    (artifact_dir / "sidecar.stderr.txt").write_text(stderr.replace(token, "[REDACTED]"), encoding="utf-8")
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True, check=False)


def chown_artifacts_to_runner(artifact_dir: Path) -> None:
    result = subprocess.run(
        ["sudo", "-n", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(artifact_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise E2EFailure(f"could not retrieve sidecar evidence: {(result.stderr or result.stdout).strip()[:500]}")


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
        "tunnel_topology": "worker -> isolated Docker sidecar SSHD -> sidecar loopback plane",
    }
    token = secrets.token_urlsafe(32)
    secret_temp = tempfile.TemporaryDirectory(prefix="aividup-pilot-cpu-secrets-")
    secret_root = Path(secret_temp.name)
    client_dir = secret_root / "client"
    sidecar_dir = secret_root / "sidecar"
    client_dir.mkdir(mode=0o700)
    sidecar_dir.mkdir(mode=0o700)
    network_name = f"aividup-pilot-cpu-net-{uuid.uuid4().hex[:10]}"
    sidecar_name = f"aividup-pilot-cpu-plane-{uuid.uuid4().hex[:10]}"
    worker_name = f"aividup-pilot-cpu-worker-{uuid.uuid4().hex[:10]}"
    network_created = False
    sidecar_started = False

    try:
        if args.image != DEFAULT_IMAGE:
            raise E2EFailure("image override is forbidden; use the pinned immutable digest")
        if shutil.which("docker") is None:
            raise E2EFailure("Docker CLI is unavailable")
        image_check = subprocess.run(["docker", "image", "inspect", args.image], capture_output=True, text=True, check=False)
        if image_check.returncode != 0:
            raise E2EFailure("pinned image is not present locally; CI must pull it by digest before this script")

        plane_module = load_plane_module()
        input_path = plane_module.make_synthetic_input(sidecar_dir / "input.mp4", seconds=2.0)
        write_private(sidecar_dir / "plane.token", token)
        plane_script = sidecar_dir / "runpod_pilot_test_control_plane.py"
        shutil.copy2(REPO_ROOT / "scripts" / "runpod_pilot_test_control_plane.py", plane_script)
        os.chmod(plane_script, 0o400)
        client_key, pinned_host_key, host_key_fingerprint, _sshd_config = prepare_tunnel_materials(client_dir, sidecar_dir)
        summary["pinned_host_key_fingerprint"] = host_key_fingerprint

        env_file = client_dir / "pod.env"
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

        run_checked([
            "docker", "network", "create", "--driver", "bridge",
            "--subnet", SIDECAR_SUBNET, "--gateway", SIDECAR_GATEWAY, network_name,
        ])
        network_created = True
        sidecar_argv = build_sidecar_argv(args.image, sidecar_name, network_name, sidecar_dir, artifact_dir)
        run_checked(sidecar_argv, timeout=300)
        sidecar_started = True
        wait_for_sidecar_ready(sidecar_name)
        tunnel_ip = get_container_ip(sidecar_name, network_name)
        if tunnel_ip != SSH_HOST_ALIAS:
            raise E2EFailure(f"sidecar IP {tunnel_ip} does not match the worker's literal SSH target {SSH_HOST_ALIAS}")

        pod_args = json.loads(POD_ARGS_PATH.read_text(encoding="utf-8"))
        docker_argv = build_docker_argv(
            pod_args,
            args.image,
            env_file,
            network_name=network_name,
        )
        docker_argv[docker_argv.index("--name") + 1] = worker_name
        summary["pod_args_sha256"] = hashlib.sha256(POD_ARGS_PATH.read_bytes()).hexdigest()
        summary["entrypoint"] = pod_args["entrypoint"]
        summary["exact_pod_args_command_used"] = True
        summary["sidecar_ipv4"] = tunnel_ip
        summary["docker_network"] = network_name

        try:
            result = subprocess.run(
                docker_argv,
                capture_output=True,
                text=True,
                timeout=args.container_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "rm", "-f", worker_name], capture_output=True, text=True, check=False)
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

        capture_and_remove_sidecar(sidecar_name, artifact_dir, token)
        sidecar_started = False
        chown_artifacts_to_runner(artifact_dir)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        summary.update(verify_evidence(evidence, output_dir, result.returncode))
        save_json(artifact_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        if sidecar_started:
            capture_and_remove_sidecar(sidecar_name, artifact_dir, token)
            sidecar_started = False
            try:
                chown_artifacts_to_runner(artifact_dir)
            except Exception as chown_error:
                summary["evidence_chown_error"] = f"{type(chown_error).__name__}: {chown_error}"
        if evidence_path.is_file():
            try:
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                summary["diagnostic_stages"] = [item.get("stage") for item in evidence.get("diagnostic_stages", [])]
                summary["claims_served"] = evidence.get("claims_served")
            except Exception as evidence_error:
                summary["evidence_error"] = f"{type(evidence_error).__name__}: {evidence_error}"
        save_json(artifact_dir / "summary.json", summary)
        print(json.dumps(summary, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if sidecar_started:
            capture_and_remove_sidecar(sidecar_name, artifact_dir, token)
        if network_created:
            subprocess.run(["docker", "network", "rm", network_name], capture_output=True, text=True, check=False)
        secret_temp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
