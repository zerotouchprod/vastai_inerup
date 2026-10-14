#!/usr/bin/env python3
"""Pull and run the exact published worker image against a CPU fake API.

This is deliberately a host-side harness: the worker entrypoint is exercised
from the OCI image, not from the checkout. It never requests a GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_IMAGE = (
    "ghcr.io/zerotouchprod/aividup-worker:2578d59dc0f8179aaea1cde434e6f1dfa2e746fb"
    "@sha256:f0bf12f71b4961c54de4b8e218ca75aa28ffdd32e1371cd1fb7aa120539279ef"
)


class FakeApiHandler(BaseHTTPRequestHandler):
    events: list[tuple[str, dict[str, Any]]] = []

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"_invalid_json": raw.decode("utf-8", "replace")}
        self.events.append((self.path, payload))
        if self.path.endswith("/claim"):
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def docker_root() -> str:
    return run(["docker", "info", "--format", "{{.DockerRootDir}}"]).stdout.strip()


def available_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def image_inspect(image: str) -> dict[str, Any]:
    raw = run(["docker", "image", "inspect", image, "--format", "{{json .}}"])
    return json.loads(raw.stdout)


def manifest_size(image: str) -> tuple[int | None, dict[str, Any]]:
    """Return compressed linux/amd64 layer bytes and raw registry metadata."""
    result = run(["docker", "buildx", "imagetools", "inspect", image, "--raw"])
    raw = json.loads(result.stdout)
    selected = raw
    if "manifests" in raw:
        candidates = [
            item
            for item in raw["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        ]
        if not candidates:
            return None, raw
        selected = run(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                f"{image.split('@', 1)[0]}@{candidates[0]['digest']}",
                "--raw",
            ]
        )
        selected = json.loads(selected.stdout)
    layers = selected.get("layers", [])
    return sum(int(layer["size"]) for layer in layers), raw


def sanitize(text: str) -> str:
    for key in ("AIVIDUP_WORKER_TOKEN", "CONTAINER_API_KEY"):
        value = os.environ.get(key)
        if value:
            text = text.replace(value, "***")
    return text[-12000:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=os.environ.get("WORKER_IMAGE", DEFAULT_IMAGE))
    parser.add_argument("--evidence", default=os.environ.get("WORKER_EVIDENCE", "evidence/worker-image-acceptance.json"))
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "image": args.image,
        "platform": "linux/amd64",
        "pull": {},
        "runtime": {},
        "decision": "FAIL",
    }
    root = docker_root()
    evidence["docker_root"] = root
    before = available_bytes(root)
    pull_started = time.monotonic()
    pull = run(["docker", "pull", "--platform", "linux/amd64", args.image])
    evidence["pull"] = {
        "exit_code": pull.returncode,
        "elapsed_seconds": round(time.monotonic() - pull_started, 3),
        "stdout": sanitize(pull.stdout),
        "stderr": sanitize(pull.stderr),
    }
    if pull.returncode != 0:
        Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(args.evidence).write_text(json.dumps(evidence, indent=2) + "\n")
        return pull.returncode

    after_pull = available_bytes(root)
    image = image_inspect(args.image)
    compressed, raw_manifest = manifest_size(args.image)
    repo_digests = image.get("RepoDigests", [])
    requested_digest = args.image.split("@", 1)[1] if "@" in args.image else None
    evidence["image_inspect"] = {
        "id": image.get("Id"),
        "repo_digests": repo_digests,
        "size_uncompressed_bytes": image.get("Size"),
        "entrypoint": image.get("Config", {}).get("Entrypoint"),
        "cmd": image.get("Config", {}).get("Cmd"),
        "working_dir": image.get("Config", {}).get("WorkingDir"),
        "labels": image.get("Config", {}).get("Labels", {}),
        "rootfs_layer_count": len(image.get("RootFS", {}).get("Layers", [])),
    }
    evidence["sizes"] = {
        "compressed_layer_bytes_linux_amd64": compressed,
        "uncompressed_image_bytes": image.get("Size"),
        "free_bytes_before_pull": before,
        "free_bytes_after_pull": after_pull,
        "pull_disk_delta_bytes": before - after_pull,
        "raw_manifest": raw_manifest,
    }

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    env = {
        "AIVIDUP_API_URL": f"http://127.0.0.1:{port}/api/worker",
        "AIVIDUP_WORKER_TOKEN": "acceptance-token",
        "AIVIDUP_GPU_INSTANCE_ID": "cpu-image-acceptance-instance",
        "AIVIDUP_GPU_LEASE_ID": "lease-image-acceptance",
        "AIVIDUP_BOOT_ID": "boot-image-acceptance",
        "AIVIDUP_PROCESSOR": "passthrough",
        "AIVIDUP_SKIP_GPU_CHECK": "1",
        "AIVIDUP_IDLE_EXIT_SECONDS": "0",
        "AIVIDUP_POLL_SECONDS": "0",
        "AIVIDUP_SELF_DESTROY": "0",
        "AIVIDUP_MAX_RESTARTS": "0",
    }
    container_started = time.monotonic()
    try:
        container = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "--network",
                "host",
                *[item for pair in env.items() for item in ("-e", f"{pair[0]}={pair[1]}")],
                args.image,
            ],
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        container = subprocess.CompletedProcess(
            args=[], returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout"
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    paths = [path for path, _payload in FakeApiHandler.events]
    expected_prefix = [
        "/api/worker/bootstrap/cpu-image-acceptance-instance",
        "/api/worker/bootstrap/cpu-image-acceptance-instance",
        "/api/worker/claim",
    ]
    stages = [payload.get("stage") for path, payload in FakeApiHandler.events if "/bootstrap/" in path]
    entrypoint = evidence["image_inspect"]["entrypoint"]
    digest_matches = any(
        item.endswith(requested_digest or "") for item in repo_digests
    )
    runtime_ok = (
        entrypoint == ["/usr/bin/tini", "--", "/usr/local/bin/worker_start.sh"]
        and container.returncode == 0
        and paths[:3] == expected_prefix
        and stages == ["started", "ready"]
        and digest_matches
    )
    evidence["runtime"] = {
        "exit_code": container.returncode,
        "elapsed_seconds": round(time.monotonic() - container_started, 3),
        "stdout": sanitize(container.stdout or ""),
        "stderr": sanitize(container.stderr or ""),
        "events": paths,
        "bootstrap_stages": stages,
        "first_claim": "/api/worker/claim" in paths,
        "entrypoint_matches_contract": entrypoint == ["/usr/bin/tini", "--", "/usr/local/bin/worker_start.sh"],
        "digest_matches_requested": digest_matches,
    }
    evidence["decision"] = "ALLOW" if runtime_ok else "FAIL"
    Path(args.evidence).parent.mkdir(parents=True, exist_ok=True)
    Path(args.evidence).write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return 0 if runtime_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
