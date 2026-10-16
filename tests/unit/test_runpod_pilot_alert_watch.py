"""Independent watchdog rules: systemd state + controller heartbeat, no provider calls."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "ops" / "runpod-pilot" / "alert-watch.py"
spec = importlib.util.spec_from_file_location("pilot_alert_watch", SCRIPT)
alert_watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert_watch)


def sample_state(**over):
    value = {
        "attempt_id": "attempt-a",
        "pod_id": "pod-a",
        "phase": "watching",
        "verified_absent": False,
        "controller_heartbeat_at": 10_000.0,
    }
    value.update(over)
    return value


def active_unit(**over):
    value = {"ActiveState": "active", "SubState": "running", "NRestarts": "0"}
    value.update(over)
    return value


def test_no_alert_before_go_even_if_state_looks_ambiguous():
    assert alert_watch.inspect_controller(
        sample_state(phase="unresolved", create_outcome_unknown=True),
        pending_incident=None,
        unit=active_unit(),
        now=20_000,
        go_armed=False,
    ) is None


def test_live_controller_with_fresh_heartbeat_does_not_alert():
    assert alert_watch.inspect_controller(
        sample_state(), pending_incident=None, unit=active_unit(), now=10_030, go_armed=True
    ) is None


def test_stale_heartbeat_alerts_even_when_unit_reports_active():
    result = alert_watch.inspect_controller(
        sample_state(), pending_incident=None, unit=active_unit(), now=10_200, go_armed=True
    )
    assert result and result[0] == "attempt-a"
    assert "heartbeat is stale" in result[1]
    assert "pod-a" in result[1]


def test_failed_systemd_unit_alerts_even_without_onfailure_marker():
    result = alert_watch.inspect_controller(
        sample_state(),
        pending_incident=None,
        unit=active_unit(ActiveState="failed"),
        now=10_030,
        go_armed=True,
    )
    assert result and "systemd unit state is failed" in result[1]


def test_ambiguous_create_alerts_without_pod_id_or_onfailure_marker():
    result = alert_watch.inspect_controller(
        sample_state(pod_id=None, phase="unresolved", create_outcome_unknown=True),
        pending_incident=None,
        unit=active_unit(),
        now=10_030,
        go_armed=True,
    )
    assert result and "create result is ambiguous" in result[1]


def test_multiple_systemd_restarts_alert_while_pod_may_exist():
    result = alert_watch.inspect_controller(
        sample_state(),
        pending_incident=None,
        unit=active_unit(NRestarts="3"),
        now=10_030,
        go_armed=True,
    )
    assert result and "restarted controller 3 times" in result[1]


def test_verified_absence_suppresses_state_based_alarm():
    assert alert_watch.inspect_controller(
        sample_state(phase="done", verified_absent=True),
        pending_incident=None,
        unit=active_unit(ActiveState="inactive"),
        now=20_000,
        go_armed=True,
    ) is None


def test_onfailure_marker_is_delivered_even_if_controller_recovered():
    result = alert_watch.inspect_controller(
        sample_state(phase="done", verified_absent=True),
        pending_incident="attempt-a",
        unit=active_unit(ActiveState="inactive"),
        now=10_030,
        go_armed=False,
    )
    assert result and "now proven absent" in result[1]
