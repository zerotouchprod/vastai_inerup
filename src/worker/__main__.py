import argparse
import time
import logging
import os
import signal
import sys
import uuid

from src.worker.client import ControlPlaneClient
from src.worker.processors import PROCESSORS
from src.worker.runner import Worker


def main() -> int:
    started = time.monotonic()
    p = argparse.ArgumentParser(
        prog="python -m src.worker", description="AIVIDUP pull worker"
    )
    p.add_argument(
        "--api",
        default=os.getenv("AIVIDUP_API_URL"),
        help="Control plane base URL, e.g. https://aividup.com/api/worker",
    )
    p.add_argument(
        "--token",
        default=os.getenv("AIVIDUP_WORKER_TOKEN"),
        help="Worker token (prefer the env var)",
    )
    p.add_argument(
        "--worker-id",
        default=os.getenv("AIVIDUP_WORKER_ID") or str(uuid.uuid4()),
        help="unique worker process UUID",
    )
    p.add_argument(
        "--provider-instance-id",
        default=os.getenv("AIVIDUP_GPU_INSTANCE_ID") or os.getenv("CONTAINER_ID") or os.getenv("VAST_CONTAINERLABEL", "").removeprefix("C."),
        help="provider-assigned GPU instance id",
    )
    p.add_argument(
        "--gpu-lease-id",
        default=os.getenv("AIVIDUP_GPU_LEASE_ID"),
        help="orchestration-assigned GPU lease UUID",
    )
    p.add_argument(
        "--boot-id",
        default=os.getenv("AIVIDUP_BOOT_ID"),
        help="orchestration-assigned boot generation UUID",
    )
    p.add_argument("--processor", choices=sorted(PROCESSORS), default="pipeline")
    p.add_argument("--poll-seconds", type=float, default=3.0)
    p.add_argument(
        "--idle-exit-seconds",
        type=float,
        default=None,
        help="Exit after this long without work",
    )
    p.add_argument(
        "--once", action="store_true", help="Handle one task (if any) and exit"
    )
    a = p.parse_args()
    missing = [
        n
        for n, v in (
            ("--api", a.api),
            ("--token", a.token),
            ("--worker-id", a.worker_id),
            ("--provider-instance-id", a.provider_instance_id),
            ("--gpu-lease-id", a.gpu_lease_id),
            ("--boot-id", a.boot_id),
        )
        if not v
    ]
    if missing:
        p.error(f"missing: {', '.join(missing)}")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Exit at once on SIGTERM: the heartbeat stops, the lease lapses and the control plane retries the chunk elsewhere.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    client = ControlPlaneClient(a.api, a.token, a.worker_id, a.provider_instance_id, a.gpu_lease_id, a.boot_id)
    revision = os.getenv("AIVIDUP_IMAGE_REVISION")
    if not revision:
        try:
            with open("/etc/aividup_revision", encoding="utf-8") as revision_file:
                revision = revision_file.read().strip()
        except OSError:
            revision = "unknown"
    revision = revision or "unknown"
    client.report_bootstrap("started", revision)
    worker = Worker(client, processor=a.processor, process_started_at=started)
    client.report_bootstrap("ready", revision)
    if a.once:
        worker.run_once()
    else:
        worker.serve(a.poll_seconds, a.idle_exit_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
