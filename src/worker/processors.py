"""Chunk processors. Each takes a chunk video file and writes the processed chunk to `dst`."""

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

log = logging.getLogger(__name__)


class ProcessorError(Exception):
    """A processing failure carrying the control-plane failure code (see FailureCode on the PHP side)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def run_cmd(cmd: List[str], lost: threading.Event, timeout: float = 3600.0) -> str:
    """Run a command; kill it if the lease is lost. Returns stderr."""
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    waited = 0.0
    while True:
        try:
            _, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            waited += 0.5
            if lost.is_set() or waited > timeout:
                proc.kill()
                proc.communicate()
                raise ProcessorError(
                    "timeout" if not lost.is_set() else "lease_expired",
                    "command aborted",
                )
    if proc.returncode != 0:
        low = (err or "").lower()
        code = "out_of_memory" if "out of memory" in low else "unknown"
        raise ProcessorError(code, (err or "")[-400:])
    return err or ""


def cut_chunk(
    input_url: str, start: float, duration: float, dst: Path, lost: threading.Event
) -> Path:
    """Frame-accurate cut (re-encode) so chunk boundaries do not drift."""
    try:
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(start),
                "-i",
                input_url,
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "12",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(dst),
            ],
            lost,
        )
    except ProcessorError as e:
        if e.code == "unknown":
            raise ProcessorError(
                "input_invalid", f"cannot read input chunk: {e}"
            ) from e
        raise
    if not dst.exists() or dst.stat().st_size == 0:
        raise ProcessorError("input_invalid", "empty chunk")
    return dst


def passthrough(
    task: Dict[str, Any], src: Path, dst: Path, lost: threading.Event
) -> None:
    dst.write_bytes(src.read_bytes())


def ffmpeg_filter(
    task: Dict[str, Any], src: Path, dst: Path, lost: threading.Event
) -> None:
    """CPU stand-in for the GPU models: fps conversion and/or scaling with ffmpeg (used for local/e2e runs)."""
    p = task.get("params", {})
    vf = []
    if p.get("target_fps"):
        vf.append(f"fps={p['target_fps']}")
    if p.get("scale"):
        vf.append(f"scale=iw*{p['scale']}:ih*{p['scale']}:flags=lanczos")
    cmd = (
        ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
        + (["-vf", ",".join(vf)] if vf else [])
        + [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            str(dst),
        ]
    )
    run_cmd(cmd, lost)


def pipeline(task: Dict[str, Any], src: Path, dst: Path, lost: threading.Event) -> None:
    """Real GPU path: the project's orchestrator on the chunk, output copied to `dst`. Needs the GPU image."""
    import shutil
    from src.domain.models import Job, UploadResult
    from src.infrastructure.config.loader import ConfigLoader
    from src.presentation.cli import create_orchestrator_from_config

    p = task.get("params", {})
    config = ConfigLoader().load(overrides={"input_url": str(src)})
    # The worker task is authoritative for processing mode and cancellation.
    # Do not construct the orchestrator with the config-file default ("both").
    config.mode = str(task.get("mode", config.mode))
    if p.get("target_fps") is not None:
        config.target_fps = p["target_fps"]
    if p.get("interp_factor") is not None:
        config.interp_factor = p["interp_factor"]
    config.b2_bucket = config.b2_key = config.b2_secret = (
        None  # never upload from the worker; it copies to `dst`
    )

    class CopyUploader:
        def upload(self, file_path, key):
            shutil.copy2(file_path, dst)
            return UploadResult(
                success=True,
                url=f"file://{dst}",
                bucket="local",
                key=key,
                size_bytes=Path(dst).stat().st_size,
            )

    t0 = time.monotonic()
    orchestrator = create_orchestrator_from_config(config)
    task.get("_timings", {})["setup_s"] = round(
        time.monotonic() - t0, 2
    )  # wiring/model objects, before frames flow
    orchestrator._uploader = CopyUploader()
    job = Job(
        job_id=task["attempt_id"],
        input_url=str(src),
        mode=task["mode"],
        scale=p.get("scale", 2.0),
        target_fps=p.get("target_fps"),
        interp_factor=p.get("interp_factor", 2.0),
    )
    if not isinstance(job.config, dict):
        job.config = {}
    job.config["cancel_event"] = lost
    job.config["progress_callback"] = task.get("_progress_callback")
    result = orchestrator.process(job)
    _collect_upscale_stats(task)
    if not getattr(result, "success", True) or not dst.exists():
        raise ProcessorError(
            "output_invalid",
            f"pipeline produced no output: {getattr(result, 'error', '')}",
        )


def _collect_upscale_stats(task: Dict[str, Any]) -> None:
    """Copy the last Real-ESRGAN run stats (batch/tile/OOM/fps/learned safe batch) into the task.

    Sent to the control plane as the optional ``upscale`` field of complete();
    kept out of ``timings`` because that map is numeric-only and summed as runtime.
    """
    try:
        from src.infrastructure.processors.realesrgan import native

        stats = dict(native.LAST_UPSCALE_STATS)
        native.LAST_UPSCALE_STATS.clear()
    except Exception:  # noqa: BLE001 - torch-less images / non-upscale modes
        return
    if stats:
        task["_upscale"] = stats
        log.info("upscale telemetry %s", json.dumps(stats, sort_keys=True))


PROCESSORS: Dict[str, Callable[[Dict[str, Any], Path, Path, threading.Event], None]] = {
    "passthrough": passthrough,
    "ffmpeg": ffmpeg_filter,
    "pipeline": pipeline,
}
