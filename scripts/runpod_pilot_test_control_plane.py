#!/usr/bin/env python3
"""Isolated single-job control plane for the RunPod RIFE pilot.

This is a throwaway stand-in for the AIVIDUP worker API. It exists so one
disposable GPU Pod can be given exactly one safe job without any access to
production: no application code, no database, no queue, no object storage, no
outbound calls. It implements only the six endpoints in
``contracts/worker-api-v1.json`` plus a local input file and a local result sink.

Hard rules enforced here:

* **Bearer token on everything.** The token is generated locally into an
  owner-only file and is never printed.
* **Exactly one job, ever.** After the single claim the plane answers 204
  forever; it cannot be repurposed into a work source.
* **The job is not parameterisable from the network.** Input, cut range, mode and
  destination are fixed by the operator at start-up. No request field can select
  a filesystem path or an arbitrary URL.
* **Loopback by default.** Binding elsewhere requires an explicit
  ``--allow-non-loopback`` acknowledgement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
BOOTSTRAP_STAGES = {"started", "ready"}


class PlaneRefused(Exception):
    """The plane refuses to start or to serve this request."""


def initialise_token(path: Path) -> str:
    """Create an owner-only token file and return the token (never logged)."""
    path = Path(path)
    if path.exists():
        raise PlaneRefused(f"refusing to overwrite existing token file {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(token + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return token


def make_synthetic_input(path: Path, seconds: float = 2.0) -> Path:
    """Generate a tiny local test clip; nothing is fetched from production."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    command = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=24:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    if not path.is_file() or path.stat().st_size == 0:
        raise PlaneRefused("synthetic input generation produced no file")
    return path


def probe_duration(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    try:
        return float(probe.stdout.strip())
    except ValueError as error:  # pragma: no cover - defensive
        raise PlaneRefused(f"cannot probe {path}") from error


class _Handler(BaseHTTPRequestHandler):
    server_version = "aividup-pilot-plane/1"
    protocol_version = "HTTP/1.1"

    # -- helpers -------------------------------------------------------
    @property
    def plane(self) -> "IsolatedControlPlane":
        return self.server.plane  # type: ignore[attr-defined]

    def log_message(self, *args: Any) -> None:  # keep stdout clean
        return

    def _send(self, status: int, payload: Optional[dict] = None, raw: bytes = b"") -> None:
        body = raw if raw else (json.dumps(payload or {}).encode() if status != 204 else b"")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _bearer(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return secrets.compare_digest(header[7:].strip(), self.plane.token)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if length <= 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    # -- routes --------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if ".." in path or "\x00" in path:
            self._send(400, {"error": "invalid path"})
            return
        body = self._body()
        if path.startswith("/api/worker/bootstrap/"):
            self._route_bootstrap(path, body)
            return
        if path == "/api/worker/claim":
            self._route_claim(body)
            return
        if path.startswith("/api/worker/attempts/"):
            self._route_attempt(path, body)
            return
        self._send(404, {"error": "unknown endpoint"})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path.startswith("/api/worker/input/"):
            name = path[len("/api/worker/input/"):]
            if not secrets.compare_digest(name, self.plane.input_token):
                self._send(404, {"error": "unknown input"})
                return
            data = self.plane.input_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send(404, {"error": "unknown endpoint"})

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if not path.startswith("/api/worker/sink/"):
            self._send(404, {"error": "unknown endpoint"})
            return
        if not self._bearer():
            self._send(401, {"error": "unauthorized"})
            return
        output_key = path.removeprefix("/api/worker/sink/")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", output_key):
            self._send(400, {"error": "invalid output key"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._send(400, {"error": "invalid length"})
            return
        if self.plane.max_output_bytes and length > self.plane.max_output_bytes:
            self._send(413, {"error": "output too large"})
            return
        data = self.rfile.read(length) if length > 0 else b""
        self.plane.record_output(output_key, data)
        self._send(200, {"ok": True})

    # -- route implementations ----------------------------------------
    def _route_bootstrap(self, path: str, body: dict) -> None:
        if not self._bearer():
            self._send(401, {"error": "unauthorized"})
            return
        stage = body.get("stage")
        if stage not in BOOTSTRAP_STAGES or not body.get("image_revision"):
            self._send(400, {"error": "invalid bootstrap report"})
            return
        self.plane.record_bootstrap(stage)
        self._send(200, {"ok": True, "retryable": False})

    def _route_claim(self, body: dict) -> None:
        if not self._bearer():
            self._send(401, {"error": "unauthorized"})
            return
        required = ("worker_id", "provider_instance_id", "gpu_lease_id", "boot_id", "claim_request_id")
        if any(not body.get(field) for field in required):
            self._send(401, {"error": "worker lease identity is incomplete"})
            return
        if not self.plane.take_job_slot():
            self._send(204)
            return
        attempt_id = str(uuid.uuid4())
        self.plane.record_claim(attempt_id, body)
        task = self.plane.build_task(attempt_id)
        self._send(
            200,
            {
                "attempt_id": attempt_id,
                "job_id": self.plane.job_id,
                "worker_id": body["worker_id"],
                "provider_instance_id": body["provider_instance_id"],
                "gpu_lease_id": body["gpu_lease_id"],
                "boot_id": body["boot_id"],
                "claim_request_id": body["claim_request_id"],
                "lease_seconds": self.plane.lease_seconds,
                "task": task,
            },
        )

    def _route_attempt(self, path: str, body: dict) -> None:
        if not self._bearer():
            self._send(401, {"error": "unauthorized"})
            return
        parts = path.split("/")
        # /api/worker/attempts/<id>/<action>
        if len(parts) != 6 or not parts[4]:
            self._send(404, {"error": "unknown endpoint"})
            return
        attempt_id, action = parts[4], parts[5]
        if not self.plane.owns(attempt_id):
            self._send(409, {"error": "stale attempt"})
            return
        if any(not body.get(field) for field in ("worker_id", "gpu_lease_id", "boot_id", "claim_request_id")):
            self._send(401, {"error": "worker lease identity is incomplete"})
            return
        if action == "heartbeat":
            self.plane.record_heartbeat(attempt_id)
            self._send(200, {"ok": True})
            return
        if action == "complete":
            output_path = body.get("output_path")
            if not isinstance(output_path, str) or not output_path:
                self._send(400, {"error": "missing output_path"})
                return
            self.plane.record_complete(attempt_id, output_path, body.get("timings") or {})
            self._send(200, {"ok": True})
            return
        if action == "fail":
            if not body.get("failure_code"):
                self._send(400, {"error": "missing failure_code"})
                return
            self.plane.record_failure(attempt_id, str(body["failure_code"]))
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "unknown endpoint"})


class IsolatedControlPlane:
    def __init__(
        self,
        token: str,
        input_path: Path,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        max_jobs: int = 1,
        evidence_path: Optional[Path] = None,
        lease_seconds: int = 300,
        mode: str = "interp",
        params: Optional[dict] = None,
        start_seconds: float = 0.0,
        max_output_bytes: int = 256 * 1024 * 1024,
        advertised_base_url: Optional[str] = None,
        output_dir: Optional[Path] = None,
    ):
        if host not in LOOPBACK_HOSTS:
            raise PlaneRefused(
                f"refusing to bind {host}: the pilot plane is loopback-only unless "
                "--allow-non-loopback is passed explicitly"
            )
        if not token:
            raise PlaneRefused("a bearer token is required")
        if max_jobs != 1:
            raise PlaneRefused("the isolated pilot plane serves exactly one job")
        self.token = token
        self.input_path = Path(input_path).resolve()
        if not self.input_path.is_file():
            raise PlaneRefused(f"input clip is missing: {self.input_path}")
        self.input_token = secrets.token_urlsafe(24)
        self.input_sha256 = hashlib.sha256(self.input_path.read_bytes()).hexdigest()
        self.host = host
        self.port = port
        self.advertised_base_url = (
            advertised_base_url.rstrip("/") if advertised_base_url else None
        )
        self.lease_seconds = lease_seconds
        self.mode = mode
        self.params = dict(params or {})
        self.start_seconds = float(start_seconds)
        self.duration_seconds = round(probe_duration(self.input_path), 2)
        self.max_output_bytes = max_output_bytes
        self.max_jobs = max_jobs
        self.job_id = f"pilot-{uuid.uuid4()}"
        self._evidence_path = Path(evidence_path) if evidence_path else None
        self.output_dir = Path(output_dir) if output_dir else None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "claims_served": 0,
            "bootstrap_stages": [],
            "heartbeats": 0,
            "outputs": [],
            "diagnostic_stages": [],
            "completed": [],
            "failures": [],
            "claims": [],
        }
        self._owned: set[str] = set()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -- evidence ------------------------------------------------------
    def evidence(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def _persist(self) -> None:
        if not self._evidence_path:
            return
        self._evidence_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._evidence_path.with_suffix(self._evidence_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self._state, indent=2, sort_keys=True))
        os.replace(temporary, self._evidence_path)

    # -- job bookkeeping ----------------------------------------------
    def take_job_slot(self) -> bool:
        with self._lock:
            if self._state["claims_served"] >= self.max_jobs:
                return False
            self._state["claims_served"] += 1
            self._persist()
            return True

    def build_task(self, attempt_id: str) -> dict:
        base = self.advertised_base_url or self.base_url
        return {
            "attempt_id": attempt_id,
            "job_id": self.job_id,
            "mode": self.mode,
            "chunk_index": 0,
            "start_seconds": self.start_seconds,
            "duration_seconds": self.duration_seconds,
            "params": dict(self.params),
            "input_url": f"{base}/input/{self.input_token}",
            "output": {
                "type": "put",
                "url": f"{base}/sink/{attempt_id}",
                "headers": {"Authorization": f"Bearer {self.token}"},
            },
        }

    def record_claim(self, attempt_id: str, body: dict) -> None:
        with self._lock:
            self._owned.add(attempt_id)
            self._state["claims"].append(
                {
                    "attempt_id": attempt_id,
                    "worker_id": body.get("worker_id"),
                    "provider_instance_id": body.get("provider_instance_id"),
                    "gpu_lease_id": body.get("gpu_lease_id"),
                    "boot_id": body.get("boot_id"),
                }
            )
            self._persist()

    def owns(self, attempt_id: str) -> bool:
        with self._lock:
            return attempt_id in self._owned

    def record_bootstrap(self, stage: str) -> None:
        with self._lock:
            self._state["bootstrap_stages"].append(stage)
            self._persist()

    def record_heartbeat(self, attempt_id: str) -> None:
        with self._lock:
            self._state["heartbeats"] += 1

    def record_complete(self, attempt_id: str, output_path: str, timings: dict) -> None:
        with self._lock:
            self._state["completed"].append(
                {"attempt_id": attempt_id, "output_path": output_path, "timings": timings}
            )
            self._persist()

    def record_failure(self, attempt_id: str, code: str) -> None:
        with self._lock:
            self._state["failures"].append({"attempt_id": attempt_id, "failure_code": code})
            self._persist()

    def record_output(self, key: str, data: bytes) -> None:
        if key.startswith("diagnostics-") and self.token:
            data = data.replace(self.token.encode(), b"[REDACTED]")
        recorded_at = time.time()
        entry = {
            "key": key,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "received_at_epoch": recorded_at,
        }
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.output_dir, 0o700)
            suffix = ".log" if key.startswith("diagnostics-") else ".mp4"
            output_path = self.output_dir / f"{key}{suffix}"
            temporary = self.output_dir / f".{key}.{uuid.uuid4().hex}.tmp"
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, output_path)
            entry["file"] = str(output_path)
        stages = re.findall(rb"(?m)^AIVIDUP_PILOT_STAGE=([a-z][a-z0-9_]*)\s*$", data)
        with self._lock:
            self._state["outputs"].append(entry)
            for raw_stage in stages:
                self._state["diagnostic_stages"].append(
                    {
                        "stage": raw_stage.decode("ascii"),
                        "key": key,
                        "file": entry.get("file"),
                        "sha256": entry["sha256"],
                        "recorded_at_epoch": recorded_at,
                    }
                )
            self._persist()

    # -- lifecycle -----------------------------------------------------
    @property
    def base_url(self) -> str:
        port = self._httpd.server_address[1] if self._httpd else self.port
        return f"http://{self.host}:{port}/api/worker"

    def start(self) -> "IsolatedControlPlane":
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.plane = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def task_params_from_cli(args: argparse.Namespace) -> dict[str, Any]:
    """Build the explicit processing parameters serialized into a pilot task."""
    return {
        "scale": args.scale,
        "interp_factor": args.interp_factor,
        "target_fps": args.target_fps,
        "strategy": args.strategy,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--init-token", type=Path, help="generate an owner-only token file and exit")
    parser.add_argument("--make-input", type=Path, help="generate the synthetic clip and exit")
    parser.add_argument("--seconds", type=float, default=2.0, help="synthetic clip length")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--advertised-base-url",
        help="base URL returned in task input/output URLs (e.g. a Pod-side SSH tunnel URL)",
    )
    parser.add_argument("--evidence", type=Path, default=Path("/tmp/aividup-pilot-plane-evidence.json"))
    parser.add_argument("--output-dir", type=Path, help="durable directory for authenticated sink payloads")
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--mode", choices=("interp", "both"), default="interp")
    parser.add_argument("--scale", type=float, default=2.0)
    parser.add_argument("--interp-factor", type=float, default=2.0)
    parser.add_argument("--strategy", choices=("interp-then-upscale", "upscale-then-interp"), default="interp-then-upscale")
    parser.add_argument("--target-fps", type=int, default=None)
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="acknowledge exposing the plane beyond loopback (needed only for direct pod access)",
    )
    args = parser.parse_args(argv)

    if args.init_token:
        token = initialise_token(args.init_token)
        print(json.dumps({"token_file": str(args.init_token), "bytes": len(token)}))
        return 0
    if args.make_input:
        path = make_synthetic_input(args.make_input, args.seconds)
        print(json.dumps({"input": str(path), "duration_seconds": round(probe_duration(path), 2)}))
        return 0
    if not args.token_file or not args.input:
        parser.error("--token-file and --input are required to serve")

    token = args.token_file.read_text().strip()
    if args.host not in LOOPBACK_HOSTS and not args.allow_non_loopback:
        print(json.dumps({"refused": f"host {args.host} requires --allow-non-loopback"}))
        return 2
    target_host = args.host
    plane = IsolatedControlPlane(
        token=token,
        input_path=args.input,
        host="127.0.0.1" if target_host not in LOOPBACK_HOSTS else target_host,
        port=args.port,
        advertised_base_url=args.advertised_base_url,
        evidence_path=args.evidence,
        output_dir=args.output_dir,
        lease_seconds=args.lease_seconds,
        mode=args.mode,
        params=task_params_from_cli(args),
    )
    if target_host not in LOOPBACK_HOSTS:
        # Explicit acknowledgement: bind on the requested interface instead.
        plane.host = target_host
    plane.start()
    print(
        json.dumps(
            {
                "serving": plane.base_url,
                "host": plane.host,
                "job_id": plane.job_id,
                "input": str(plane.input_path),
                "input_sha256": plane.input_sha256,
                "duration_seconds": plane.duration_seconds,
                "evidence": str(args.evidence),
                "jobs": 1,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        plane.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
