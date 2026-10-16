#!/usr/bin/env python3
"""CPU-only one-job E2E through the real restricted SSH local-forward; never calls RunPod."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.runpod_pilot_test_control_plane import IsolatedControlPlane  # noqa: E402
from src.worker.client import ControlPlaneClient  # noqa: E402
from src.worker.runner import Worker  # noqa: E402


class OutputCapturingPlane(IsolatedControlPlane):
    """Persist the actual received PUT body so its digest can be checked independently."""

    def __init__(self, *args, output_dir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_dir = output_dir
        self.output_paths: dict[str, Path] = {}

    def record_output(self, key: str, data: bytes) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.output_dir / f"{key}.mp4"
        temporary = path.with_suffix(".mp4.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        self.output_paths[key] = path
        super().record_output(key, data)


def wait_for_forward(port: int, process: subprocess.Popen, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"SSH forward exited early with status {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("SSH local forward did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="isolated two-second MP4")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--ssh-key", type=Path, required=True)
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--ssh-user", default="aividup-pilot-tunnel")
    parser.add_argument("--server-port", type=int, default=8099)
    parser.add_argument("--forward-port", type=int, default=18099)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if not args.input.is_file() or not args.token_file.is_file():
        parser.error("input and token files must exist")
    if args.ssh_key.stat().st_mode & 0o077:
        parser.error("SSH private key must not be group/world accessible")
    if not shutil.which("ssh") or not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        parser.error("ssh, ffmpeg, and ffprobe must be installed")
    output_dir_has_files = args.output_dir.exists() and any(args.output_dir.iterdir())
    if args.evidence.exists() or output_dir_has_files:
        parser.error("evidence and output directory must be fresh; never overwrite a prior one-shot run")

    token = args.token_file.read_text().strip()
    if not token:
        parser.error("empty plane token")
    advertised = f"http://127.0.0.1:{args.forward_port}/api/worker"
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(output_dir, 0o700)

    plane = OutputCapturingPlane(
        token=token,
        input_path=args.input,
        host="127.0.0.1",
        port=args.server_port,
        advertised_base_url=advertised,
        evidence_path=args.evidence,
        output_dir=output_dir,
        mode="interp",
        params={"interp_factor": 2.0},
    )
    ssh_command = [
        "ssh", "-N",
        "-L", f"127.0.0.1:{args.forward_port}:127.0.0.1:{args.server_port}",
        "-i", str(args.ssh_key),
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={args.known_hosts}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=3",
        f"{args.ssh_user}@{args.ssh_host}",
    ]
    tunnel = None
    try:
        plane.start()
        tunnel = subprocess.Popen(ssh_command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        wait_for_forward(args.forward_port, tunnel)

        import requests

        unauthorized = requests.post(f"{advertised}/claim", json={}, timeout=5)
        if unauthorized.status_code != 401:
            raise AssertionError(f"tunnel auth probe returned HTTP {unauthorized.status_code}, expected 401")

        client = ControlPlaneClient(
            advertised,
            token,
            worker_id="cpu-ssh-forward-e2e",
            provider_instance_id="local-no-gpu",
            gpu_lease_id="cpu-e2e-lease",
            boot_id="cpu-e2e-boot",
        )
        client.report_bootstrap("started", "cpu-e2e")
        client.report_bootstrap("ready", "cpu-e2e")
        worker = Worker(client, processor="passthrough", workdir=output_dir)
        started = time.monotonic()
        claimed_and_completed = worker.run_once()
        elapsed = round(time.monotonic() - started, 3)
        no_second_job = worker.run_once() is False

        evidence = plane.evidence()
        if not claimed_and_completed or not no_second_job:
            raise AssertionError("worker did not complete exactly one job")
        if evidence["claims_served"] != 1 or len(evidence["completed"]) != 1:
            raise AssertionError("expected one claimed and completed task")
        if evidence["failures"]:
            raise AssertionError(f"plane recorded worker failures: {evidence['failures']}")
        if len(evidence["outputs"]) != 1:
            raise AssertionError("expected exactly one output PUT")

        output_meta = evidence["outputs"][0]
        output_path = plane.output_paths[output_meta["key"]]
        actual_bytes = output_path.stat().st_size
        actual_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        if actual_bytes <= 0 or output_meta["bytes"] != actual_bytes:
            raise AssertionError("persisted output is empty or byte count differs from evidence")
        if output_meta["sha256"] != actual_sha256:
            raise AssertionError("persisted output SHA-256 differs from sink evidence")

        summary = {
            "result": "PASS",
            "runpod_api_called": False,
            "gpu_used": False,
            "server_listener": f"127.0.0.1:{args.server_port}",
            "advertised_base_url": advertised,
            "ssh_forward": "PASS",
            "unauthenticated_probe_http": unauthorized.status_code,
            "flow": ["claim", "ffmpeg_input_cut", "cpu_passthrough", "PUT_output", "complete"],
            "claims_served": evidence["claims_served"],
            "output_bytes": actual_bytes,
            "output_sha256": actual_sha256,
            "evidence_sha256": output_meta["sha256"],
            "sha256_matches": True,
            "worker_timings": evidence["completed"][0]["timings"],
            "end_to_end_seconds": elapsed,
            "no_second_job_served": no_second_job,
            "input_sha256": plane.input_sha256,
            "input_duration_seconds": plane.duration_seconds,
            "evidence_file": str(args.evidence),
            "output_file": str(output_path),
        }
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 0
    finally:
        if tunnel is not None:
            tunnel.terminate()
            try:
                tunnel.wait(timeout=10)
            except subprocess.TimeoutExpired:
                tunnel.kill()
                tunnel.wait(timeout=5)
        plane.stop()


if __name__ == "__main__":
    raise SystemExit(main())
