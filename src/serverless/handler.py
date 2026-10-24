"""EXPERIMENT (aividup-serverless-blackwell): RunPod Serverless wrapper around the pull worker's chunk pipeline (RIFE + Real-ESRGAN).

Input: {"input_url": "<http(s) url>" | "lavfi", "start": 0, "duration": 10, "mode": "both",
        "params": {"scale": 2, "target_fps": 60}}
Optional "output_put_url": presigned PUT (R2) for the encoded result; upload time is measured.
{"diag": true} returns torch/CUDA capability + arch list and a GPU kernel smoke test with full traceback.
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


def _diag():
    import platform
    import traceback

    out = {"python": platform.python_version()}
    try:
        import torch

        out.update(torch=torch.__version__, torch_cuda=torch.version.cuda, cudnn=torch.backends.cudnn.version(),
                   cuda_available=torch.cuda.is_available(), arch_list=torch.cuda.get_arch_list())
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            out.update(gpu=p.name, capability=list(torch.cuda.get_device_capability(0)),
                       total_mem_gb=round(p.total_memory / 1e9, 1), sm_count=p.multi_processor_count,
                       mig=os.environ.get("NVIDIA_VISIBLE_DEVICES", "").startswith("MIG"))
            for name, fn in (
                ("matmul", lambda: (torch.randn(512, 512, device="cuda") @ torch.randn(512, 512, device="cuda")).sum().item()),
                ("conv2d_half", lambda: torch.nn.functional.conv2d(torch.randn(1, 3, 64, 64, device="cuda").half(),
                                                                   torch.randn(8, 3, 3, 3, device="cuda").half()).sum().item()),
                ("grid_sample", lambda: torch.nn.functional.grid_sample(torch.randn(1, 3, 32, 32, device="cuda"),
                                                                        torch.zeros(1, 32, 32, 2, device="cuda"),
                                                                        align_corners=True).sum().item()),
            ):
                try:
                    fn()
                    torch.cuda.synchronize()
                    out[name] = "ok"
                except Exception:
                    out[name] = traceback.format_exc()[-2000:]
    except Exception:
        out["import_error"] = traceback.format_exc()[-2000:]
    try:
        out["nvidia_smi"] = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=20).stdout[-1000:]
    except Exception as e:
        out["nvidia_smi"] = repr(e)
    return out


_CALLS = {"n": 0}


def handler(job):
    from src.worker.processors import cut_chunk, pipeline

    t0 = time.time()
    _CALLS["n"] += 1
    inp = job.get("input") or {}
    if inp.get("diag"):
        return {"diag": _diag(), "process_start_epoch": round(PROCESS_START, 3), "call_index_in_worker": _CALLS["n"], **_IMPORTED}
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
        if inp.get("output_put_url") and timings["output_bytes"] > 0:
            import requests

            t = time.monotonic()
            with open(dst, "rb") as fh:
                r = requests.put(inp["output_put_url"], data=fh, headers={"Content-Type": "video/mp4"}, timeout=300)
            timings["upload_s"] = round(time.monotonic() - t, 2)
            timings["upload_status"] = r.status_code
        try:
            timings["output_duration_s"] = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(dst)],
                capture_output=True, text=True, timeout=30).stdout.strip() or 0)
        except Exception:
            pass
    timings["handler_total_s"] = round(time.time() - t0, 2)
    timings["worker_id"] = os.environ.get("RUNPOD_POD_ID")
    return timings


if __name__ == "__main__":
    import runpod

    logging_root = __import__("logging")
    logging_root.basicConfig(level=logging_root.INFO)
    _warm_imports()
    import torch

    if torch.cuda.is_available():
        print("gpu", _IMPORTED.get("gpu"), "capability", torch.cuda.get_device_capability(0),
              "torch", torch.__version__, "cuda", torch.version.cuda, "arch", torch.cuda.get_arch_list(), flush=True)
    runpod.serverless.start({"handler": handler})
