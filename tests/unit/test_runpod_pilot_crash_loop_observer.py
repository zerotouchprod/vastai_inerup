"""Fail-closed tests for the SSH crash-loop observer."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

OBSERVER_PATH = (
    Path(__file__).resolve().parents[2]
    / "ops"
    / "runpod-pilot"
    / "crash-loop-observer.py"
)
spec = importlib.util.spec_from_file_location("runpod_crash_loop_observer", OBSERVER_PATH)
if spec is None or spec.loader is None:
    raise ModuleNotFoundError(f"crash-loop observer is not implemented: {OBSERVER_PATH}")
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def test_journalctl_since_formats_supported_local_timestamp():
    formatted = observer.format_journal_since(1792153496)
    assert "T" not in formatted
    assert "+00:00" not in formatted
    assert len(formatted) == 19


def test_journal_query_error_is_not_interpreted_as_zero_sessions():
    def failed(command, **kwargs):
        assert "--since" in command
        return subprocess.CompletedProcess(command, 1, "", "Failed to parse timestamp")

    with pytest.raises(observer.ObservabilityFailure, match="OBSERVABILITY_FAILURE"):
        observer.accepted_tunnel_sessions(1792153496, runner=failed, command_prefix=[])


def test_journalctl_stderr_read_error_is_not_zero_sessions():
    def read_error(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "", "Failed to read journal: permission denied")

    with pytest.raises(observer.ObservabilityFailure, match="OBSERVABILITY_FAILURE"):
        observer.accepted_tunnel_sessions(1792153496, runner=read_error, command_prefix=[])


def test_real_journalctl_rejects_iso_timestamp_and_observer_surfaces_it():
    if shutil.which("journalctl") is None:
        pytest.skip("journalctl is unavailable on this test host")
    with pytest.raises(observer.ObservabilityFailure, match="OBSERVABILITY_FAILURE") as error:
        observer.query_journalctl("2026-10-16T12:24:56+00:00", command_prefix=[])
    assert "parse timestamp" in str(error.value).lower()


def test_observer_persists_failure_marker_and_stops_controller_on_journal_error(tmp_path, monkeypatch):
    import sys
    import time

    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"attempt_id":"attempt-test","phase":"watching","pod_id":"pod-test"}'
    )
    monkeypatch.setattr(
        observer,
        "accepted_tunnel_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            observer.ObservabilityFailure("OBSERVABILITY_FAILURE: journalctl test error")
        ),
    )
    stopped = []
    monkeypatch.setattr(
        observer,
        "stop_controller",
        lambda unit: stopped.append(unit) or subprocess.CompletedProcess([unit], 0, "", ""),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(OBSERVER_PATH),
            "--state-file",
            str(state_file),
            "--plane-evidence",
            str(tmp_path / "plane-evidence.json"),
            "--started-at-epoch",
            str(time.time()),
        ],
    )

    assert observer.main() == 3
    assert stopped == ["aividup-runpod-pilot.service"]
    assert (tmp_path / "alert-pending").read_text().strip().startswith("observer-failure-")
    incidents = list(tmp_path.glob("observer-failure-*.json"))
    assert len(incidents) == 1
    import json

    assert json.loads(incidents[0].read_text())["observability_status"] == "OBSERVABILITY_FAILURE"


def test_invalid_provider_timestamp_is_observability_failure(monkeypatch, tmp_path):
    import sys
    import time

    state_file = tmp_path / "state.json"
    state_file.write_text(
        '{"attempt_id":"attempt-bad-time","phase":"watching","pod_id":"pod-test","provider_created_at":"bad-time"}'
    )
    stopped = []
    monkeypatch.setattr(
        observer,
        "stop_controller",
        lambda unit: stopped.append(unit) or subprocess.CompletedProcess([unit], 0, "", ""),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(OBSERVER_PATH),
            "--state-file",
            str(state_file),
            "--plane-evidence",
            str(tmp_path / "plane-evidence.json"),
            "--started-at-epoch",
            str(time.time()),
        ],
    )

    assert observer.main() == 3
    assert stopped == ["aividup-runpod-pilot.service"]
    incidents = list(tmp_path.glob("observer-failure-*.json"))
    assert len(incidents) == 1
    import json

    assert json.loads(incidents[0].read_text())["observability_status"] == "OBSERVABILITY_FAILURE"


def test_observer_timeout_detects_no_tunnel_before_cuda():
    reason = observer.stage_timeout_reason(
        {"provider_created_at": 1_000.0},
        {"diagnostic_stages": [], "outputs": []},
        now=1_301.0,
    )
    assert reason == "STAGE_TIMEOUT: tunnel_ready was not recorded within 300 seconds of create"


def test_stop_controller_command_error_is_observability_failure(monkeypatch):
    def missing_systemctl(*args, **kwargs):
        raise FileNotFoundError("systemctl missing")

    monkeypatch.setattr(observer.subprocess, "run", missing_systemctl)
    with pytest.raises(observer.ObservabilityFailure, match="OBSERVABILITY_FAILURE"):
        observer.stop_controller("aividup-runpod-pilot.service")


def test_incident_persistence_survives_missing_logger(tmp_path, monkeypatch):
    def missing_logger(*args, **kwargs):
        raise FileNotFoundError("logger not installed")

    monkeypatch.setattr(observer.subprocess, "run", missing_logger)
    record = observer.persist_incident(tmp_path / "state.json", "attempt-log-test", "OBSERVABILITY_FAILURE: test")
    assert record.is_file()
    assert (tmp_path / "alert-pending").read_text().strip() == "attempt-log-test"


def test_observer_stage_timeout_names_first_missing_transition():
    state = {"provider_created_at": 1_000.0}
    plane = {
        "diagnostic_stages": [
            {"stage": "tunnel_ready", "recorded_at_epoch": 1_000.0},
        ],
        "outputs": [],
    }
    reason = observer.stage_timeout_reason(state, plane, now=1_061.0)
    assert reason is not None
    assert "STAGE_TIMEOUT" in reason
    assert "http_probe_pass" in reason


def test_observer_times_out_if_preflight_log_is_not_persisted():
    state = {"provider_created_at": 1_000.0}
    plane = {
        "diagnostic_stages": [
            {"stage": "tunnel_ready", "recorded_at_epoch": 1_000.0},
            {"stage": "http_probe_pass", "recorded_at_epoch": 1_001.0},
            {"stage": "bootstrap_started", "recorded_at_epoch": 1_002.0},
            {"stage": "checkpoint_verified", "recorded_at_epoch": 1_003.0},
            {"stage": "worker_started", "recorded_at_epoch": 1_004.0},
            {"stage": "cuda_preflight", "recorded_at_epoch": 1_005.0},
        ],
        "outputs": [],
    }
    reason = observer.stage_timeout_reason(state, plane, now=1_126.0)
    assert reason is not None
    assert "stdout/stderr was not persisted" in reason


def test_three_reconnects_inside_window_are_a_crash_loop():
    now = 1_000.0
    assert observer.restart_loop_detected([920.0, 950.0, 980.0], now=now)
    assert not observer.restart_loop_detected([900.0, 940.0, 970.0], now=now)
    assert not observer.restart_loop_detected([980.0, 990.0], now=now)
