"""EXPERIMENT: RunPod Serverless wrapper around the pull worker's chunk pipeline (RIFE + Real-ESRGAN).

Input: {"input_url": "<http(s) url>" | "lavfi", "start": 0, "duration": 10, "mode": "both",
        "params": {"scale": 2, "target_fps": 60}}
Returns measured timings only (no upload); output size proves the pipeline produced a file.
"""

import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PROCESS_START = time.time()
_IMPORTED = {}


def _warm_imports():
    t = time.monotonic()
    import torch  # noqa: F401

    _IMPORTED["torch_import_s"] = round(time.monotonic() - t, 2)
    _IMPORTED["cuda"] = bool(torch.cuda.is_available())
    _IMPORTED["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None


def _synthetic(dst: Path, duration: float) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={duration}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)],
        check=True,
    )


_CALLS = {"n": 0}


def handler(job):
    from src.worker.processors import cut_chunk, pipeline

    t0 = time.time()
    _CALLS["n"] += 1
    inp = job.get("input") or {}
    duration = float(inp.get("duration", 10))
    lost = threading.Event()
    timings = {"handler_start_epoch": round(t0, 3), "process_start_epoch": round(PROCESS_START, 3),
               "call_index_in_worker": _CALLS["n"], **_IMPORTED}
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.mp4", Path(d) / "out.mp4"
        t = time.monotonic()
        url = str(inp.get("input_url", "lavfi"))
        if inp.get("input_b64"):
            import base64

            src.write_bytes(base64.b64decode(inp["input_b64"]))
        elif url == "lavfi":
            _synthetic(src, duration)
        else:
            cut_chunk(url, float(inp.get("start", 0)), duration, src, lost)
        timings["input_s"] = round(time.monotonic() - t, 2)
        task = {"attempt_id": job.get("id", "sls"), "mode": inp.get("mode", "both"),
                "params": inp.get("params", {"scale": 2, "target_fps": 60}), "_timings": timings}
        t = time.monotonic()
        timings["first_gpu_compute_epoch"] = round(time.time(), 3)
        import io
        import logging

        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.setLevel(logging.INFO)
        logging.getLogger().addHandler(h)
        try:
            pipeline(task, src, dst, lost)
        except Exception as e:  # experiment: surface the cause (log tail only, no env)
            return {"error": f"{type(e).__name__}: {e}", "log_tail": buf.getvalue()[-3000:],
                    "disk_free_gb": round(__import__("shutil").disk_usage(d).free / 1e9, 1), **timings}
        finally:
            logging.getLogger().removeHandler(h)
        timings["pipeline_s"] = round(time.monotonic() - t, 2)
        timings["output_bytes"] = dst.stat().st_size if dst.exists() else 0
    timings["handler_total_s"] = round(time.time() - t0, 2)
    timings["worker_id"] = os.environ.get("RUNPOD_POD_ID")
    return timings


if __name__ == "__main__":
    import runpod

    logging_root = __import__("logging")
    logging_root.basicConfig(level=logging_root.INFO)
    _warm_imports()
    runpod.serverless.start({"handler": handler})
