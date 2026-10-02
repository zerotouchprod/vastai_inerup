import argparse
import logging
import os
import sys

from src.worker.client import ControlPlaneClient
from src.worker.processors import PROCESSORS
from src.worker.runner import Worker


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m src.worker", description="AIVIDUP pull worker")
    p.add_argument("--api", default=os.getenv("AIVIDUP_API_URL"), help="Control plane base URL, e.g. https://aividup.com/api/worker")
    p.add_argument("--token", default=os.getenv("AIVIDUP_WORKER_TOKEN"), help="Worker token (prefer the env var)")
    p.add_argument("--worker-id", default=os.getenv("AIVIDUP_WORKER_ID") or os.getenv("CONTAINER_ID"), help="GPU instance id this worker runs on")
    p.add_argument("--processor", choices=sorted(PROCESSORS), default="pipeline")
    p.add_argument("--poll-seconds", type=float, default=3.0)
    p.add_argument("--idle-exit-seconds", type=float, default=None, help="Exit after this long without work")
    p.add_argument("--once", action="store_true", help="Handle one task (if any) and exit")
    a = p.parse_args()
    missing = [n for n, v in (("--api", a.api), ("--token", a.token), ("--worker-id", a.worker_id)) if not v]
    if missing:
        p.error(f"missing: {', '.join(missing)}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker(ControlPlaneClient(a.api, a.token, a.worker_id), processor=a.processor)
    if a.once:
        worker.run_once()
    else:
        worker.serve(a.poll_seconds, a.idle_exit_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
