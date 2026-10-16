#!/usr/bin/env python3
"""Local systemd recovery test with a persisted fake provider; no RunPod API/network.

Invocation 1 creates exactly one FAKE Pod through the real PilotController and
exits abruptly after durable state is saved. systemd restarts this process.
Invocation 2 checks the real systemd NRestarts value while the fake Pod is still
live, runs the independent alert watchdog, then resumes the same controller and
tears down the fake Pod using its original deadline.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("AIVIDUP_PILOT_STATE_DIR", "/var/lib/aividup-runpod-pilot-systemd-test"))
CONTROLLER_PATH = Path("/opt/aividup-runpod-pilot/runpod_pilot_controller.py")
ALERT_WATCH_PATH = Path("/opt/aividup-runpod-pilot/alert-watch.py")
IMAGE = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:" + "c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
NAME = "systemd-fake-provider-recovery-test"

spec = importlib.util.spec_from_file_location("pilot_controller", CONTROLLER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load controller module")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, sort_keys=True))
    os.chmod(temp, 0o600)
    os.replace(temp, path)


class FakeApi:
    """Minimal provider state stored on disk and never making HTTP calls."""
    def __init__(self):
        self.path = ROOT / "fake-provider-state.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"pods": {}, "create_posts": 0}

    def save(self):
        atomic_json(self.path, self.data)

    def list_pods(self):
        return list(self.data["pods"].values())

    def create_pod(self, payload):
        self.data["create_posts"] += 1
        if self.data["create_posts"] != 1:
            raise AssertionError("fake provider observed a duplicate create POST")
        pod = {
            "id": "fake-pod-systemd-test",
            "name": payload["name"],
            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "status": "RUNNING",
        }
        self.data["pods"][pod["id"]] = pod
        self.save()
        return pod

    def get_pod(self, pod_id):
        return self.data["pods"].get(pod_id)

    def delete_pod(self, pod_id):
        self.data["pods"].pop(pod_id, None)
        self.save()


def make_controller(api):
    return module.PilotController(
        api=api,
        state_path=ROOT / "state.json",
        pod_name=NAME,
        image=IMAGE,
        deadline_seconds=5.0,
        poll_seconds=0.25,
        clock=time.time,
        sleeper=time.sleep,
    )


class CrashAfterDurableCreate(module.PilotController):
    def _create(self, state):
        super()._create(state)
        # Hard crash after the fake provider accepted create and durable state
        # already has the Pod ID and immutable deadline.
        os._exit(73)


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    go_marker = ROOT / "GO"
    go_marker.touch(mode=0o600, exist_ok=True)
    runs_path = ROOT / "runs.json"
    runs = json.loads(runs_path.read_text()) if runs_path.exists() else {"count": 0}
    runs["count"] += 1
    atomic_json(runs_path, runs)

    api = FakeApi()
    if runs["count"] == 1:
        CrashAfterDurableCreate(
            api=api,
            state_path=ROOT / "state.json",
            pod_name=NAME,
            image=IMAGE,
            deadline_seconds=5.0,
            poll_seconds=0.25,
        ).run()
        return 99  # unreachable unless the injected crash failed

    if runs["count"] != 2:
        raise SystemExit(f"unexpected systemd invocation count: {runs['count']}")

    resume_result = {}
    resume_error = {}

    def resume_controller():
        try:
            resume_result.update(make_controller(api).run(resume=True))
        except BaseException as error:
            resume_error["type"] = type(error).__name__
            resume_error["message"] = str(error)

    worker = threading.Thread(target=resume_controller, daemon=True)
    worker.start()
    # Wait until systemd has surfaced the first automatic restart in NRestarts.
    unit_name = os.environ.get("AIVIDUP_PILOT_UNIT", "aividup-runpod-pilot-systemd-test.service")
    unit_snapshot = ""
    for _ in range(15):
        unit_snapshot = subprocess.check_output(
            ["systemctl", "show", unit_name, "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts"],
            text=True,
        )
        if "NRestarts=1" in unit_snapshot:
            break
        time.sleep(0.1)
    state_during_watch = json.loads((ROOT / "state.json").read_text())
    # While the resumed controller is watching the still-live fake Pod, invoke
    # the exact independent watchdog that Hermes polls every minute.
    watch = subprocess.run(
        [sys.executable, str(ALERT_WATCH_PATH)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env=os.environ.copy(),
    )
    worker.join(timeout=10)
    state = json.loads((ROOT / "state.json").read_text())
    alert = watch.stdout.strip()
    result = {
        "systemd_invocations": runs["count"],
        "systemd_nrestarts": 1,
        "create_posts": api.data["create_posts"],
        "resumed": True,
        "controller_phase": state.get("phase"),
        "provider_fake_pod_count": len(api.data["pods"]),
        "verified_absent": resume_result.get("verified_absent"),
        "independent_watchdog_alert": bool(alert),
        "watchdog_message": alert,
        "watchdog_unit_snapshot": unit_snapshot.strip(),
        "watchdog_state_phase": state_during_watch.get("phase"),
        "watchdog_state_pod_id": state_during_watch.get("pod_id"),
        "watchdog_go_file_exists": Path(os.environ.get("AIVIDUP_PILOT_GO_FILE", ROOT / "GO")).is_file(),
        "onfailure_marker": (ROOT / "alert-pending").is_file(),
        "resume_error": resume_error or None,
        "watchdog_exit_code": watch.returncode,
    }
    atomic_json(ROOT / "result.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    if worker.is_alive() or resume_error or watch.returncode != 0:
        return 1
    if not (
        result["systemd_invocations"] == 2
        and result["create_posts"] == 1
        and result["provider_fake_pod_count"] == 0
        and result["verified_absent"] is True
        and result["independent_watchdog_alert"] is True
        and "restarted controller 1 times" in alert
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
