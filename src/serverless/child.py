"""Child process for one chunk: fetch input + RIFE/Real-ESRGAN pipeline. Runs in its own process group so the
handler can kill it (and every ffmpeg/torch thread under it) on cancel or deadline.

Usage: python -m src.serverless.child <spec.json>   (spec written by the handler; result in spec["result_path"])
"""

import json
import logging
import sys
import threading
import time
from pathlib import Path


def main(spec_path: str) -> int:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(message)s"
    )
    spec = json.loads(Path(spec_path).read_text())
    from src.serverless import encoder as enc
    from src.serverless.handler import fetch_input, run_pipeline

    enc.apply_to_assembler(spec.get("encoder") or enc.X264)
    timings = {}
    lost = threading.Event()
    src, dst = Path(spec["src"]), Path(spec["dst"])
    t = time.monotonic()
    fetch_input(spec, src, lost)
    timings["input_s"] = round(time.monotonic() - t, 2)
    print("AIVIDUP_STAGE pipeline", file=sys.stderr, flush=True)
    task = {
        "attempt_id": spec["attempt_id"],
        "mode": spec["mode"],
        "params": spec["params"],
        "_timings": timings,
    }
    timings["first_gpu_compute_epoch"] = round(time.time(), 3)
    t = time.monotonic()
    run_pipeline(task, src, dst, lost)
    timings["pipeline_s"] = round(time.monotonic() - t, 2)
    Path(spec["result_path"]).write_text(json.dumps({"timings": timings}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
