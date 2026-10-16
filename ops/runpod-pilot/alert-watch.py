#!/usr/bin/env python3
"""Telegram alert watchdog for systemd failure, dead controller, or stale heartbeat."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

ROOT = Path(os.environ.get("AIVIDUP_PILOT_STATE_DIR", "/var/lib/aividup-runpod-pilot"))
GO_FILE = Path(os.environ.get("AIVIDUP_PILOT_GO_FILE", "/etc/aividup-runpod-pilot/GO"))
UNIT = os.environ.get("AIVIDUP_PILOT_UNIT", "aividup-runpod-pilot.service")
HEARTBEAT_STALE_SECONDS = 120
RESTART_WARNING_COUNT = 1


def inspect_controller(
    state: dict,
    *,
    pending_incident: Optional[str],
    unit: dict,
    now: float,
    go_armed: bool,
    heartbeat_stale_seconds: int = HEARTBEAT_STALE_SECONDS,
    restart_warning_count: int = RESTART_WARNING_COUNT,
) -> Optional[tuple[str, str]]:
    """Return (incident_id, message) when an operator must be paged."""
    incident = pending_incident or state.get("attempt_id")
    if not incident:
        return None
    phase = state.get("phase") or "missing-state"
    pod_id = state.get("pod_id")
    verified = state.get("verified_absent")
    ambiguous = bool(state.get("create_outcome_unknown"))

    # The durable OnFailure marker is authoritative and is delivered even if the
    # controller recovered before this poll. The note will then say so.
    if pending_incident:
        if verified is True or phase == "done":
            return incident, (
                f"RunPod pilot controller restart/failure for attempt {incident}; "
                f"pod {pod_id or '(unknown)'} is now proven absent. Inspect journal for the incident."
            )
        return incident, (
            f"CRITICAL: RunPod pilot controller failed for attempt {incident}; "
            f"pod {pod_id or '(unknown; reconcile by name)'}, phase={phase}, "
            f"verified_absent={verified}. It may still be billing; inspect provider inventory now."
        )

    # A probe is relevant only after an explicit GO and while there may be a live
    # or ambiguously-created Pod. It must remain silent during free preparation.
    if not go_armed:
        return None
    if verified is True or phase in {"done", "no_pod"}:
        return None
    if not pod_id and not ambiguous:
        return None

    active = unit.get("ActiveState", "unknown")
    restarts = int(unit.get("NRestarts", "0") or 0)
    heartbeat = state.get("controller_heartbeat_at")
    try:
        age = now - float(heartbeat)
    except (TypeError, ValueError):
        age = float("inf")

    reason = None
    if phase == "unresolved" or phase == "ambiguous_create_pending" or ambiguous and not pod_id:
        reason = "create result is ambiguous and provider inventory has not established absence"
    elif active not in {"active", "activating", "reloading"}:
        reason = f"systemd unit state is {active}"
    elif age > heartbeat_stale_seconds:
        reason = f"controller heartbeat is stale ({int(age)}s)"
    elif restarts >= restart_warning_count:
        reason = f"systemd has restarted controller {restarts} times"

    if reason is None:
        return None
    severity = "CRITICAL" if verified is not True else "WARNING"
    return incident, (
        f"{severity}: RunPod pilot watchdog: {reason}; attempt={incident}, "
        f"pod={pod_id or '(unknown; search by unique name)'}, phase={phase}, "
        f"verified_absent={verified}. Check controller and provider inventory."
    )


def _unit_snapshot() -> dict:
    result = subprocess.run(
        ["systemctl", "show", UNIT, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts"],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if result.returncode != 0:
        return {"ActiveState": "unavailable", "NRestarts": "0"}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def main() -> int:
    pending = ROOT / "alert-pending"
    sent = ROOT / "alert-sent"
    state_path = ROOT / "state.json"
    try:
        pending_incident = pending.read_text().strip() if pending.is_file() else None
    except OSError:
        pending_incident = None
    try:
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    except Exception:
        state = {}

    decision = inspect_controller(
        state,
        pending_incident=pending_incident,
        unit=_unit_snapshot(),
        now=time.time(),
        go_armed=GO_FILE.is_file(),
    )
    if decision is None:
        return 0
    incident, message = decision
    if sent.is_file() and sent.read_text().strip() == incident:
        return 0

    ROOT.mkdir(parents=True, exist_ok=True)
    tmp = sent.with_suffix(".tmp")
    tmp.write_text(incident + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, sent)
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
