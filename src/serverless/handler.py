"""RunPod Serverless handler for one aividup chunk (RIFE v4.26 + Real-ESRGAN via the pull worker's pipeline).

Contract (schema 1) - job["input"]:
  input_url        http(s) URL of the source video, or "lavfi" for a synthetic clip (self-test)
  input_b64        alternative to input_url: base64 of a small chunk
  start, duration  seconds; duration 0 < d <= MAX_DURATION_S
  mode             "both" | "upscale" | "interp"
  params           {"scale": 2, "target_fps": 60, "interp_factor": 2}
  chunk_id         optional caller id, echoed back (used for no-double-execution checks)
  output_put_url   optional presigned PUT (R2) for the encoded chunk
  telemetry_put_url optional presigned PUT (R2) for a JSON telemetry/error record
  diag / selfcheck true -> return the self-check report only (no processing)

Success output: ok=true, output_sha256/bytes/frames/duration_s, encoder, selfcheck summary, timings.
Failure output: "error" (RunPod marks the job FAILED, the rest stays in output) + failure_code, error_type,
traceback, log_tail, telemetry; GPU/CUDA failures set refresh_worker so a poisoned worker is recycled.
Presigned URLs and environment values are never echoed back.
"""

import base64
import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from src.serverless import encoder as enc
from src.serverless import selfcheck

SCHEMA = 1
MAX_DURATION_S = 120.0
MODES = ("both", "upscale", "interp")
PROCESS_START = time.time()
log = logging.getLogger("aividup.serverless")

_STATE: Dict[str, Any] = {
    "calls": 0,
    "selfcheck": None,
    "encoder": None,
    "probe": None,
    "seen": {},
}


class InputError(ValueError):
    pass


def validate(inp: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(inp, dict):
        raise InputError("input must be an object")
    url = str(inp.get("input_url", "lavfi" if not inp.get("input_b64") else ""))
    if (
        not inp.get("input_b64")
        and url != "lavfi"
        and not url.startswith(("http://", "https://"))
    ):
        raise InputError("input_url must be http(s) or 'lavfi'")
    try:
        start = float(inp.get("start", 0))
        duration = float(inp.get("duration", 10))
    except (TypeError, ValueError):
        raise InputError("start/duration must be numbers")
    if start < 0 or not (0 < duration <= MAX_DURATION_S):
        raise InputError(f"need start >= 0 and 0 < duration <= {MAX_DURATION_S}")
    mode = inp.get("mode", "both")
    if mode not in MODES:
        raise InputError(f"mode must be one of {MODES}")
    params = inp.get("params", {"scale": 2, "target_fps": 60})
    if not isinstance(params, dict):
        raise InputError("params must be an object")
    for k in ("output_put_url", "telemetry_put_url"):
        v = inp.get(k)
        if v is not None and not str(v).startswith("https://"):
            raise InputError(f"{k} must be https")
    return {
        "input_url": url,
        "input_b64": inp.get("input_b64"),
        "start": start,
        "duration": duration,
        "mode": mode,
        "params": params,
        "chunk_id": inp.get("chunk_id"),
        "output_put_url": inp.get("output_put_url"),
        "telemetry_put_url": inp.get("telemetry_put_url"),
    }


def startup(torch_mod=None, run=subprocess.run) -> Dict[str, Any]:
    """Self-check + NVENC probe once per worker process; logged as one line."""
    if _STATE["selfcheck"] is None:
        t = time.monotonic()
        rep = selfcheck.collect(torch_mod=torch_mod, run=run)
        rep["selfcheck_s"] = round(time.monotonic() - t, 2)
        probe = enc.probe_nvenc(run=run)
        choice = enc.select_encoder(probe)
        _STATE.update(selfcheck=rep, probe=probe, encoder=choice)
        log.info(
            "%s encoder=%s(%s)",
            selfcheck.summary_line(rep),
            choice["encoder"],
            choice["reason"],
        )
    return _STATE["selfcheck"]


def _selfcheck_summary() -> Dict[str, Any]:
    rep = _STATE["selfcheck"] or {}
    keys = (
        "ok",
        "reason",
        "gpu",
        "arch",
        "capability",
        "mig_profile",
        "vram_total_gb",
        "vram_free_gb",
        "torch",
        "torch_cuda",
        "revision",
        "selfcheck_s",
    )
    return {k: rep[k] for k in keys if k in rep}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe_output(p: Path, run=subprocess.run) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        r = run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_packets",
                "-show_entries",
                "stream=nb_read_packets,codec_name,width,height,avg_frame_rate:format=duration",
                "-of",
                "json",
                str(p),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        d = json.loads(r.stdout or "{}")
        s = (d.get("streams") or [{}])[0]
        out = {
            "output_frames": int(s.get("nb_read_packets", 0) or 0),
            "output_codec": s.get("codec_name"),
            "output_width": s.get("width"),
            "output_height": s.get("height"),
            "output_fps": s.get("avg_frame_rate"),
            "output_duration_s": float((d.get("format") or {}).get("duration", 0) or 0),
        }
    except Exception as e:  # noqa: BLE001
        out["probe_error"] = f"{type(e).__name__}"
    return out


def _put(
    url: str,
    path: Optional[Path] = None,
    body: Optional[bytes] = None,
    ctype: str = "video/mp4",
) -> int:
    import requests

    if path is not None:
        with open(path, "rb") as fh:
            return requests.put(
                url, data=fh, headers={"Content-Type": ctype}, timeout=300
            ).status_code
    return requests.put(
        url, data=body, headers={"Content-Type": ctype}, timeout=60
    ).status_code


def _synthetic(dst: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=640x360:rate=30:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(dst),
        ],
        check=True,
        timeout=120,
    )


def fetch_input(spec: Dict[str, Any], dst: Path, lost: threading.Event) -> None:
    if spec["input_b64"]:
        dst.write_bytes(base64.b64decode(spec["input_b64"]))
    elif spec["input_url"] == "lavfi":
        _synthetic(dst, spec["duration"])
    else:
        from src.worker.processors import cut_chunk

        cut_chunk(spec["input_url"], spec["start"], spec["duration"], dst, lost)


def run_pipeline(
    task: Dict[str, Any], src: Path, dst: Path, lost: threading.Event
) -> None:
    from src.worker.processors import pipeline

    pipeline(task, src, dst, lost)


def _failure_code(e: BaseException) -> str:
    code = getattr(e, "code", None)
    if code:
        return str(code)
    if isinstance(e, InputError):
        return "input_invalid"
    low = str(e).lower()
    if "out of memory" in low:
        return "out_of_memory"
    if "cuda" in low or "no kernel image" in low:
        return "gpu_error"
    return "unknown"


def handler(job: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.time()
    _STATE["calls"] += 1
    job_id = str(job.get("id", "local"))
    raw = job.get("input") or {}
    base = {
        "schema": SCHEMA,
        "job_id": job_id,
        "chunk_id": raw.get("chunk_id") if isinstance(raw, dict) else None,
        "call_index_in_worker": _STATE["calls"],
        "worker_id": os.environ.get("RUNPOD_POD_ID"),
        "process_start_epoch": round(PROCESS_START, 3),
        "handler_start_epoch": round(t0, 3),
    }
    # Same job id twice in one worker = RunPod re-delivered it; record it so the E2E can assert no double execution.
    base["repeat_delivery"] = job_id in _STATE["seen"]
    _STATE["seen"][job_id] = _STATE["seen"].get(job_id, 0) + 1
    startup()
    base["selfcheck"] = _selfcheck_summary()
    base["encoder"] = (_STATE["encoder"] or {}).get("encoder")
    base["encoder_reason"] = (_STATE["encoder"] or {}).get("reason")
    if isinstance(raw, dict) and (raw.get("diag") or raw.get("selfcheck")):
        return {
            **base,
            "ok": bool(base["selfcheck"].get("ok")),
            "diag": _STATE["selfcheck"],
            "nvenc": _STATE["probe"],
        }

    timings: Dict[str, Any] = {}
    buf = io.StringIO()
    lh = logging.StreamHandler(buf)
    lh.setLevel(logging.INFO)
    root = logging.getLogger()
    root.addHandler(lh)
    spec: Dict[str, Any] = {}
    stage = "validate"
    try:
        spec = validate(raw)
        if not base["selfcheck"].get("ok"):
            raise RuntimeError(
                f"gpu self-check failed: {base['selfcheck'].get('reason')}"
            )
        enc.apply_to_assembler(base["encoder"] or enc.X264)
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "in.mp4", Path(d) / "out.mp4"
            lost = threading.Event()
            stage = "input"
            t = time.monotonic()
            fetch_input(spec, src, lost)
            timings["input_s"] = round(time.monotonic() - t, 2)
            stage = "pipeline"
            task = {
                "attempt_id": job_id,
                "mode": spec["mode"],
                "params": spec["params"],
                "_timings": timings,
            }
            timings["first_gpu_compute_epoch"] = round(time.time(), 3)
            t = time.monotonic()
            run_pipeline(task, src, dst, lost)
            timings["pipeline_s"] = round(time.monotonic() - t, 2)
            if not dst.exists() or dst.stat().st_size == 0:
                raise RuntimeError("pipeline produced no output")
            stage = "verify"
            res = {
                "output_bytes": dst.stat().st_size,
                "output_sha256": sha256_file(dst),
                **probe_output(dst),
            }
            used = [
                ln
                for ln in buf.getvalue().splitlines()
                if "Assembling video with encoder:" in ln
            ]
            if used:
                res["encoder_used"] = used[-1].rsplit(":", 1)[-1].strip()
            if spec["output_put_url"]:
                stage = "upload"
                t = time.monotonic()
                res["upload_status"] = _put(spec["output_put_url"], path=dst)
                timings["upload_s"] = round(time.monotonic() - t, 2)
                if not 200 <= res["upload_status"] < 300:
                    raise RuntimeError(f"output upload HTTP {res['upload_status']}")
        timings["handler_total_s"] = round(time.time() - t0, 2)
        out = {**base, "ok": True, **res, "timings": timings}
        _telemetry(spec, out)
        return out
    except (
        BaseException
    ) as e:  # noqa: BLE001 - every failure must come back with its context
        code = _failure_code(e)
        timings["handler_total_s"] = round(time.time() - t0, 2)
        out = {
            **base,
            "ok": False,
            "error": f"{code}: {type(e).__name__}: {str(e)[:500]}",
            "failure_code": code,
            "failed_stage": stage,
            "error_type": type(e).__name__,
            "traceback": traceback.format_exc()[-4000:],
            "log_tail": buf.getvalue()[-4000:],
            "timings": timings,
        }
        try:
            out["disk_free_gb"] = round(
                shutil.disk_usage(tempfile.gettempdir()).free / 1e9, 1
            )
        except OSError:
            pass
        if (
            code in ("gpu_error", "out_of_memory")
            or stage == "validate"
            and "self-check" in str(e)
        ):
            out["refresh_worker"] = True
        _telemetry(spec or (raw if isinstance(raw, dict) else {}), out)
        if not isinstance(e, Exception):
            raise
        return out
    finally:
        root.removeHandler(lh)


def _telemetry(spec: Dict[str, Any], out: Dict[str, Any]) -> None:
    url = spec.get("telemetry_put_url") if isinstance(spec, dict) else None
    if not url or not str(url).startswith("https://"):
        return
    try:
        body = json.dumps(
            {k: v for k, v in out.items() if k != "refresh_worker"}, default=str
        ).encode()
        out["telemetry_upload_status"] = _put(url, body=body, ctype="application/json")
    except Exception as e:  # noqa: BLE001
        out["telemetry_upload_status"] = f"failed: {type(e).__name__}"


if __name__ == "__main__":
    import runpod

    logging.basicConfig(level=logging.INFO)
    startup()
    runpod.serverless.start({"handler": handler})
