"""The pull loop: claim -> heartbeat while processing -> verify -> upload -> report."""
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests

from src.worker.client import ControlPlaneClient, LeaseLost
from src.worker.processors import PROCESSORS, ProcessorError, cut_chunk

log = logging.getLogger("worker")


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def deliver(output: Dict[str, Any], src: Path) -> str:
    """Store the result where the control plane told us to; returns the reported output path."""
    if output["type"] == "file":
        dest = Path(output["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return str(dest)
    if output["type"] == "put":
        last: Optional[Exception] = None
        for attempt in range(3):
            try:
                # Extra signed headers from the presigned URL; Host is set by the HTTP client itself
                headers = {"Content-Type": "video/mp4", **{k: v for k, v in (output.get("headers") or {}).items() if k.lower() != "host"}}
                with open(src, "rb") as fh:
                    r = requests.put(output["url"], data=fh, timeout=300, headers=headers)
                r.raise_for_status()
                return output["url"].split("?", 1)[0]
            except requests.RequestException as e:  # transient storage errors are retried, then reported as retryable
                last = e
                time.sleep(2 ** attempt)
        raise ProcessorError("unknown", f"upload failed: {last}")
    raise ProcessorError("input_invalid", f"unknown output type {output['type']!r}")


class Worker:
    def __init__(self, client: ControlPlaneClient, processor: str = "pipeline", workdir: Optional[Path] = None,
                 heartbeat_seconds: Optional[float] = None, expected_tolerance: float = 0.15,
                 process_started_at: Optional[float] = None):
        self._client = client
        self._processor = PROCESSORS[processor]
        self._workdir = Path(workdir or tempfile.gettempdir())
        self._hb_override = heartbeat_seconds
        self._tol = expected_tolerance
        self._process_started = process_started_at if process_started_at is not None else time.monotonic()
        self._first_claim_reported = False

    def run_once(self) -> bool:
        """Handle at most one task. Returns False when there was nothing to do."""
        claimed = self._client.claim()
        if claimed is None:
            return False
        claimed_at = time.monotonic()
        attempt_id, task = claimed["attempt_id"], claimed["task"]
        interval = self._hb_override or max(1.0, claimed.get("lease_seconds", 300) / 4)
        lost, stop = threading.Event(), threading.Event()

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    self._client.heartbeat(attempt_id)
                except LeaseLost:
                    log.warning("lease lost for %s - aborting", attempt_id)
                    lost.set()
                    return
                except requests.RequestException as e:  # control plane blip: keep working, lease has slack
                    log.warning("heartbeat failed: %s", e)

        threading.Thread(target=beat, daemon=True).start()
        work = Path(tempfile.mkdtemp(prefix=f"chunk_{task.get('chunk_index', 0)}_", dir=self._workdir))
        try:
            self._client.heartbeat(attempt_id)  # first beat immediately: claim -> running is visible
            chunk_in, chunk_out = work / "in.mp4", work / "out.mp4"
            timings: Dict[str, float] = {}
            if not self._first_claim_reported:  # container start -> first task in hand (python boot, not image pull)
                timings["boot_to_claim_s"] = round(claimed_at - self._process_started, 2)
                self._first_claim_reported = True
            t = time.monotonic()
            cut_chunk(task["input_url"], task["start_seconds"], task["duration_seconds"], chunk_in, lost)
            timings["cut_s"], t = round(time.monotonic() - t, 2), time.monotonic()
            task["_timings"] = timings  # processors may add finer phases (e.g. model_load_s)
            self._processor(task, chunk_in, chunk_out, lost)
            timings["process_s"], t = round(time.monotonic() - t, 2), time.monotonic()
            if lost.is_set():
                raise LeaseLost("lost during processing")
            self._verify(task, chunk_out)
            timings["verify_s"], t = round(time.monotonic() - t, 2), time.monotonic()
            out_path = deliver(task["output"], chunk_out)
            timings["upload_s"] = round(time.monotonic() - t, 2)
            timings["work_s"] = round(time.monotonic() - claimed_at, 2)
            self._client.complete(attempt_id, out_path, timings)
            log.info("chunk %s done -> %s timings=%s", task.get("chunk_index"), out_path, timings)
        except LeaseLost:
            log.warning("dropping attempt %s (reaped by control plane)", attempt_id)
        except ProcessorError as e:
            if lost.is_set():  # aborted because the lease was lost: the attempt is no longer ours to report
                log.warning("dropping attempt %s (lease lost)", attempt_id)
            else:
                self._report_failure(attempt_id, e.code, str(e))
        except Exception as e:  # noqa: BLE001 - anything else is an unknown, retryable failure
            self._report_failure(attempt_id, "unknown", repr(e))
        finally:
            stop.set()
            shutil.rmtree(work, ignore_errors=True)
        return True

    def _verify(self, task: Dict[str, Any], out: Path) -> None:
        if not out.exists() or out.stat().st_size == 0:
            raise ProcessorError("output_invalid", "no output produced")
        want, got = float(task["duration_seconds"]), probe_duration(out)
        if abs(got - want) > max(0.2, self._tol * want):
            raise ProcessorError("output_invalid", f"duration {got:.2f}s != expected {want:.2f}s")

    def _report_failure(self, attempt_id: str, code: str, message: str) -> None:
        log.error("attempt %s failed (%s): %s", attempt_id, code, message)
        try:
            self._client.fail(attempt_id, code)
        except LeaseLost:
            pass

    def serve(self, poll_seconds: float = 3.0, idle_exit_seconds: Optional[float] = None,
              should_stop: Callable[[], bool] = lambda: False) -> None:
        """Loop until idle for `idle_exit_seconds` (stop paying for an idle GPU) or told to stop."""
        idle_since = time.monotonic()
        while not should_stop():
            if self.run_once():
                idle_since = time.monotonic()
                continue
            if idle_exit_seconds is not None and time.monotonic() - idle_since >= idle_exit_seconds:
                log.info("idle for %.0fs - exiting", idle_exit_seconds)
                return
            time.sleep(poll_seconds)
