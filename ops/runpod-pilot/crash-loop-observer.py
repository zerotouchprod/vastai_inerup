#!/usr/bin/env python3
"""Fail-closed monitor for RunPod pilot tunnel restart loops and journal errors."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

TUNNEL_USER = "aividup-pilot-tunnel"


class ObservabilityFailure(RuntimeError):
    """The observer cannot reliably read the event source; never interpret it as no events."""


def format_journal_since(epoch: float) -> str:
    """Return journalctl's supported local timestamp syntax (not ISO 8601)."""
    return datetime.fromtimestamp(float(epoch)).strftime("%Y-%m-%d %H:%M:%S")


def query_journalctl(
    since: str,
    *,
    runner: Callable = subprocess.run,
    command_prefix: tuple[str, ...] | list[str] = ("sudo", "-n"),
) -> str:
    command = [
        *command_prefix,
        "journalctl",
        "-u",
        "ssh",
        "-u",
        "sshd",
        "--since",
        since,
        "--no-pager",
        "-o",
        "json",
    ]
    result = runner(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode != 0 or (result.stderr or "").strip():
        detail = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise ObservabilityFailure(
            f"OBSERVABILITY_FAILURE: journalctl exited {result.returncode}: {detail[:500]}"
        )
    return result.stdout


def accepted_tunnel_sessions(
    started_at: float,
    *,
    runner: Callable = subprocess.run,
    command_prefix: tuple[str, ...] | list[str] = ("sudo", "-n"),
) -> list[float]:
    since = format_journal_since(started_at)
    text = query_journalctl(since, runner=runner, command_prefix=command_prefix)
    matches: list[float] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ObservabilityFailure(
                f"OBSERVABILITY_FAILURE: invalid journal JSON at line {line_number}: {exc}"
            ) from exc
        message = str(entry.get("MESSAGE", ""))
        if f"Accepted publickey for {TUNNEL_USER} from " not in message:
            continue
        try:
            matches.append(float(entry["__REALTIME_TIMESTAMP"]) / 1_000_000)
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservabilityFailure(
                f"OBSERVABILITY_FAILURE: accepted SSH event lacks a valid timestamp at line {line_number}"
            ) from exc
    return sorted(matches)


def stage_timeout_reason(state: dict, plane: dict, *, now: float) -> Optional[str]:
    """Return a fail-closed reason when an expected startup stage stops progressing."""
    start = state.get("_create_requested_epoch") or state.get("provider_created_at")
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
        except ValueError as exc:
            raise ObservabilityFailure(f"OBSERVABILITY_FAILURE: invalid provider createdAt: {exc}") from exc
    if start is None:
        return None
    try:
        start = float(start)
    except (TypeError, ValueError) as exc:
        raise ObservabilityFailure("OBSERVABILITY_FAILURE: invalid create reservation timestamp") from exc

    stages = plane.get("diagnostic_stages") or []
    latest: dict[str, float] = {}
    for item in stages:
        try:
            stage = str(item["stage"])
            stamp = float(item["recorded_at_epoch"])
            latest[stage] = max(latest.get(stage, stamp), stamp)
        except (KeyError, TypeError, ValueError) as exc:
            raise ObservabilityFailure(f"OBSERVABILITY_FAILURE: malformed diagnostic stage: {exc}") from exc

    if "tunnel_ready" not in latest:
        if now - start > 300:
            return "STAGE_TIMEOUT: tunnel_ready was not recorded within 300 seconds of create"
        return None

    transitions = [
        ("tunnel_ready", "http_probe_pass", 60),
        ("http_probe_pass", "bootstrap_started", 60),
        ("bootstrap_started", "checkpoint_verified", 300),
        ("checkpoint_verified", "worker_started", 180),
        ("worker_started", "cuda_preflight", 120),
    ]
    for previous, following, timeout in transitions:
        if previous in latest and following not in latest and now - latest[previous] > timeout:
            return f"STAGE_TIMEOUT: {following} was not recorded within {timeout} seconds after {previous}"

    if "cuda_preflight" in latest:
        logs = [
            item for item in plane.get("outputs", [])
            if "cuda-preflight" in str(item.get("key", ""))
        ]
        if not logs and now - latest["cuda_preflight"] > 120:
            return "STAGE_TIMEOUT: CUDA/RIFE preflight stdout/stderr was not persisted within 120 seconds"
    return None


def restart_loop_detected(
    sessions: list[float], *, now: float, threshold: int = 3, window_seconds: float = 90.0
) -> bool:
    recent = [stamp for stamp in sessions if 0 <= now - stamp <= window_seconds]
    return len(recent) >= threshold


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def persist_incident(state_file: Path, incident_id: str, reason: str) -> Path:
    root = state_file.parent
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", incident_id)[:96] or "unknown"
    incident = {
        "incident_id": incident_id,
        "observability_status": (
            "OBSERVABILITY_FAILURE"
            if reason.startswith("OBSERVABILITY_FAILURE")
            else "STAGE_TIMEOUT"
            if reason.startswith("STAGE_TIMEOUT")
            else "CRASH_LOOP"
        ),
        "reason": reason,
        "recorded_at_epoch": time.time(),
    }
    record_path = root / f"observer-failure-{safe_id}.json"
    _atomic_write(record_path, (json.dumps(incident, sort_keys=True, indent=2) + "\n").encode())
    pending = root / "alert-pending"
    _atomic_write(pending, (incident_id + "\n").encode())
    try:
        subprocess.run(
            ["logger", "-p", "daemon.crit", "-t", "aividup-runpod-pilot-observer", reason[:800]],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    return record_path


def stop_controller(unit: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["sudo", "-n", "systemctl", "stop", unit],
            capture_output=True,
            text=True,
            timeout=150,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservabilityFailure(
            f"OBSERVABILITY_FAILURE: could not stop controller unit {unit}: {exc}"
        ) from exc
    if result.returncode != 0:
        raise ObservabilityFailure(
            f"OBSERVABILITY_FAILURE: could not stop controller unit {unit}: "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )
    return result


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.is_file() else {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ObservabilityFailure(f"OBSERVABILITY_FAILURE: cannot read {path}: {exc}") from exc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--plane-evidence", type=Path, required=True)
    parser.add_argument("--started-at-epoch", type=float, required=True)
    parser.add_argument("--unit", default="aividup-runpod-pilot.service")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--restart-threshold", type=int, default=3)
    parser.add_argument("--restart-window-seconds", type=float, default=90.0)
    parser.add_argument("--max-run-seconds", type=float, default=2000.0)
    args = parser.parse_args(argv)

    started = args.started_at_epoch
    end = started + args.max_run_seconds
    print("observer_started; journal_time_format=YYYY-MM-DD HH:MM:SS", flush=True)
    while time.time() < end:
        try:
            state = _read_json(args.state_file)
            if state.get("phase") in {"done", "no_pod"}:
                print(f"controller_terminal_phase={state.get('phase')}", flush=True)
                return 0
            provider_created = state.get("_create_requested_epoch") or state.get("provider_created_at")
            if isinstance(provider_created, str):
                try:
                    provider_created = datetime.fromisoformat(provider_created.replace("Z", "+00:00")).timestamp()
                except ValueError as exc:
                    raise ObservabilityFailure(
                        f"OBSERVABILITY_FAILURE: invalid provider createdAt: {exc}"
                    ) from exc
            try:
                query_start = float(provider_created) if provider_created is not None else started
            except (TypeError, ValueError) as exc:
                raise ObservabilityFailure("OBSERVABILITY_FAILURE: invalid create reservation timestamp") from exc

            plane = _read_json(args.plane_evidence)
            failures = plane.get("failures") or []
            if failures:
                incident = str(state.get("attempt_id") or f"plane-failure-{int(time.time())}")
                reason = f"worker failure recorded by isolated plane: {json.dumps(failures[-1], sort_keys=True)}"
                persist_incident(args.state_file, incident, reason)
                stop_controller(args.unit)
                return 2

            sessions = accepted_tunnel_sessions(query_start)
            now = time.time()
            if restart_loop_detected(
                sessions,
                now=now,
                threshold=args.restart_threshold,
                window_seconds=args.restart_window_seconds,
            ):
                incident = str(state.get("attempt_id") or f"ssh-restart-loop-{int(now)}")
                reason = (
                    f"SSH tunnel restart loop: {len([s for s in sessions if now-s <= args.restart_window_seconds])} "
                    f"accepted sessions in {args.restart_window_seconds:g}s"
                )
                persist_incident(args.state_file, incident, reason)
                stop_controller(args.unit)
                return 2

            stage_reason = stage_timeout_reason(state, plane, now=now)
            if stage_reason:
                incident = str(state.get("attempt_id") or f"stage-timeout-{int(now)}")
                persist_incident(args.state_file, incident, stage_reason)
                stop_controller(args.unit)
                return 4
        except ObservabilityFailure as exc:
            incident = f"observer-failure-{int(time.time())}"
            persist_incident(args.state_file, incident, str(exc))
            try:
                stop_controller(args.unit)
            except ObservabilityFailure as stop_error:
                print(str(stop_error), file=__import__("sys").stderr, flush=True)
            print(str(exc), file=__import__("sys").stderr, flush=True)
            return 3
        time.sleep(max(0.2, args.poll_seconds))
    print("observer_max_runtime_reached", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
