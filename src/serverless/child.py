"""Child process for one chunk: fetch input + RIFE/Real-ESRGAN pipeline. Runs in its own process group so the
handler can kill it (and every ffmpeg/torch thread under it) on cancel or deadline.

Usage: python -m src.serverless.child <spec.json>   (spec written by the handler; result in spec["result_path"])
"""

import json
import hashlib
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def main(spec_path: str) -> int:
    try:  # child output is a file tee'd by the handler: flush every line
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    spec = json.loads(Path(spec_path).read_text())
    os.environ["AIVIDUP_LOG_JOB_ID"] = str(spec.get("job_id") or spec["attempt_id"])
    os.environ["AIVIDUP_LOG_CHUNK_ID"] = str(spec.get("chunk_id", "-"))
    from src.serverless import encoder as enc
    from src.serverless.handler import fetch_input, run_pipeline

    enc.apply_to_assembler(spec.get("encoder") or enc.X264)
    timings = {}
    lost = threading.Event()
    src, dst = Path(spec["src"]), Path(spec["dst"])
    t = time.monotonic()
    fetch_input(spec, src, lost)
    timings["input_s"] = round(time.monotonic() - t, 2)
    digest = hashlib.sha256()
    with src.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    input_sha256 = digest.hexdigest()
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(src),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    input_duration_s = float(probe.stdout.strip())
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
    Path(spec["result_path"]).write_text(
        json.dumps(
            {
                "timings": timings,
                "input_sha256": input_sha256,
                "input_duration_s": input_duration_s,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
