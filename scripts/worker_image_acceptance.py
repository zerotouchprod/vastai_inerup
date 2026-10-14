#!/usr/bin/env python3
"""CPU-only acceptance probe for the real worker entrypoint and pull protocol."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    events: list[tuple[str, dict]] = []

    def log_message(self, format, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.events.append((self.path, payload))
        if self.path.endswith("/claim"):
            self.send_response(204)
        else:
            self.send_response(200)
            self.send_header("content-type", "application/json")
        self.end_headers()
        if not self.path.endswith("/claim"):
            self.wfile.write(b"{}")


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "AIVIDUP_API_URL": f"http://127.0.0.1:{server.server_port}/api/worker",
        "AIVIDUP_WORKER_TOKEN": "acceptance-token",
        "AIVIDUP_GPU_INSTANCE_ID": "cpu-acceptance-instance",
        "AIVIDUP_GPU_LEASE_ID": "lease-acceptance",
        "AIVIDUP_BOOT_ID": "boot-acceptance",
        "AIVIDUP_PROCESSOR": "passthrough",
        "AIVIDUP_IDLE_EXIT_SECONDS": "0",
        "AIVIDUP_POLL_SECONDS": "0",
        "AIVIDUP_SKIP_GPU_CHECK": "1",
    }
    try:
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/worker_start.sh")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    paths = [path for path, _ in Handler.events]
    expected = [
        "/api/worker/bootstrap/cpu-acceptance-instance",
        "/api/worker/bootstrap/cpu-acceptance-instance",
        "/api/worker/claim",
    ]
    if result.returncode != 0:
        raise SystemExit(f"worker exited {result.returncode}:\n{result.stdout}\n{result.stderr}")
    if paths[:3] != expected:
        raise SystemExit(f"unexpected worker protocol events: {paths!r}\n{result.stdout}\n{result.stderr}")
    stages = [payload.get("stage") for path, payload in Handler.events if "/bootstrap/" in path]
    if stages != ["started", "ready"]:
        raise SystemExit(f"unexpected bootstrap stages: {stages!r}")
    print(json.dumps({"decision": "ALLOW", "events": paths, "bootstrap_stages": stages, "stdout": result.stdout}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
