"""Behavioural tests for the external one-shot RunPod pilot controller (no network, no GPU)."""

import json
from pathlib import Path

import pytest

from scripts.runpod_pilot_controller import (
    AmbiguousCreate,
    PilotController,
    PodDeleteError,
    REFUSED_EXIT_CODE,
    UNRESOLVED_EXIT_CODE,
)

IMAGE = (
    "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@"
    "sha256:c775c62ade2d1851074751d761195aa6ace2895ed51af268b5f877535117475b"
)
NAME = "aividup-rife-pilot-abcd1234"
DEADLINE_SECONDS = 1800
HOUR = 3600


class FakeClock:
    def __init__(self, now):
        self.now = float(now)
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += max(0.0, float(seconds))


class FakeApi:
    """Stand-in RunPod client with injectable failure modes."""

    def __init__(self, clock, pods=None):
        self.clock = clock
        self.pods = {p["id"]: dict(p) for p in (pods or [])}
        self.posts = 0
        self.lists = 0
        self.gets = 0
        self.deletes = []
        self.create_error = None
        self.create_pod_id = "pod-new-1"
        self.create_created_at = None
        self.delete_errors = []
        self.list_error = None
        self.list_error_after = None
        self.get_error_after = None

    # -- helpers -------------------------------------------------------
    def _all(self):
        if self.list_error:
            raise self.list_error
        if self.list_error_after is not None and self.lists > self.list_error_after:
            raise RuntimeError("inventory unavailable")
        return [dict(p) for p in self.pods.values()]

    def create_pod(self, payload):
        self.posts += 1
        created_at = self.create_created_at or self.clock.time()
        pod = {
            "id": self.create_pod_id,
            "name": payload["name"],
            "createdAt": _iso(created_at),
            "status": "RUNNING",
            "image": payload.get("image"),
        }
        if self.create_error is not None:
            # Simulate an ambiguous outcome: the provider may still have created it.
            if getattr(self.create_error, "pod_was_created", False):
                self.pods[pod["id"]] = pod
            raise self.create_error
        self.pods[pod["id"]] = pod
        return dict(pod)

    def list_pods(self):
        self.lists += 1
        return self._all()

    def get_pod(self, pod_id):
        self.gets += 1
        if self.get_error_after is not None and self.gets > self.get_error_after:
            raise RuntimeError("inventory unavailable")
        return dict(self.pods.get(pod_id)) if pod_id in self.pods else None

    def delete_pod(self, pod_id):
        self.deletes.append((pod_id, self.clock.now))
        if self.delete_errors:
            error = self.delete_errors.pop(0)
            if error is not None:
                raise error
        self.pods.pop(pod_id, None)


def _iso(epoch):
    import datetime

    return datetime.datetime.fromtimestamp(
        epoch, datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def make_controller(tmp_path, api, clock, **over):
    kwargs = dict(
        api=api,
        state_path=tmp_path / "state.json",
        pod_name=NAME,
        image=IMAGE,
        deadline_seconds=DEADLINE_SECONDS,
        poll_seconds=30,
        clock=clock.time,
        sleeper=clock.sleep,
    )
    kwargs.update(over)
    return PilotController(**kwargs)


def load_state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


# ---------------------------------------------------------------------------
# create / durable identity
# ---------------------------------------------------------------------------


def test_create_persists_pod_id_and_absolute_deadline(tmp_path):
    clock = FakeClock(1_000_000)
    api = FakeApi(clock)
    controller = make_controller(tmp_path, api, clock)

    report = controller.run()

    assert api.posts == 1, "exactly one create request is allowed"
    state = load_state(tmp_path)
    assert state["pod_id"] == "pod-new-1"
    assert state["deadline_at"] == pytest.approx(1_000_000 + DEADLINE_SECONDS)
    assert state["phase"] == "done"
    assert state["verified_absent"] is True
    assert report["exit_code"] == 0
    assert report["pod_id"] == "pod-new-1"
    assert api.deletes and api.deletes[0][0] == "pod-new-1"


def test_state_is_written_before_the_create_request(tmp_path):
    """A crash mid-create must still leave a durable record of the attempt."""
    clock = FakeClock(500_000)
    api = FakeApi(clock)
    seen = {}
    original = api.create_pod

    def spy(payload):
        seen.update(load_state(tmp_path))
        return original(payload)

    api.create_pod = spy
    make_controller(tmp_path, api, clock).run()

    assert seen["pod_name"] == NAME
    assert seen["phase"] == "creating"
    assert seen["attempt_id"]


def test_deadline_uses_provider_created_at_not_local_clock(tmp_path):
    """A skewed local clock must not silently extend the pod's life."""
    clock = FakeClock(900_000)
    api = FakeApi(clock)
    api.create_pod_id = "pod-x"
    # The provider says the Pod appeared 20 minutes ago, i.e. before our request.
    api.create_created_at = 900_000 - 20 * 60
    api.create_error = AmbiguousCreate("timeout", pod_was_created=True)

    controller = make_controller(tmp_path, api, clock)
    controller.run()

    state = load_state(tmp_path)
    assert state["pod_id"] == "pod-x"
    # 20 minutes already elapsed -> only 10 minutes of life remain.
    assert state["deadline_at"] == pytest.approx(900_000 - 1200 + DEADLINE_SECONDS)
    assert api.deletes[-1][1] >= state["deadline_at"]


# ---------------------------------------------------------------------------
# ambiguous create
# ---------------------------------------------------------------------------


def test_ambiguous_create_does_not_repeat_post_and_adopts_pod(tmp_path):
    clock = FakeClock(2_000_000)
    api = FakeApi(clock)
    api.create_pod_id = "pod-adopted"
    api.create_error = AmbiguousCreate("connection reset", pod_was_created=True)

    report = make_controller(tmp_path, api, clock).run()

    assert api.posts == 1, "an ambiguous create must never be retried blindly"
    assert report["pod_id"] == "pod-adopted"
    assert report["exit_code"] == 0
    assert api.deletes and api.deletes[0][0] == "pod-adopted"


def test_ambiguous_create_without_orphan_ends_clean(tmp_path):
    clock = FakeClock(3_000_000)
    api = FakeApi(clock)  # create fails and nothing was created
    api.create_error = AmbiguousCreate("gateway timeout")

    report = make_controller(tmp_path, api, clock).run()

    assert api.posts == 1
    assert api.lists >= 2, "inventory must be re-checked before declaring no pod"
    assert report["pod_id"] is None
    assert report["exit_code"] == 0
    assert load_state(tmp_path)["phase"] == "no_pod"
    assert api.deletes == []


def test_ambiguous_create_with_unreachable_inventory_refuses(tmp_path):
    clock = FakeClock(3_100_000)
    api = FakeApi(clock)
    api.create_error = AmbiguousCreate("timeout")
    # Preflight inventory works; the outage begins right after the create.
    api.list_error_after = 1

    report = make_controller(tmp_path, api, clock).run()

    assert api.posts == 1
    assert report["exit_code"] == UNRESOLVED_EXIT_CODE
    assert report["verified_absent"] is False


# ---------------------------------------------------------------------------
# deadline + teardown
# ---------------------------------------------------------------------------


def test_pod_is_deleted_at_the_deadline(tmp_path):
    clock = FakeClock(4_000_000)
    api = FakeApi(clock)
    make_controller(tmp_path, api, clock, poll_seconds=60).run()

    assert api.deletes[0][1] >= 4_000_000 + DEADLINE_SECONDS
    assert api.deletes[0][1] <= 4_000_000 + DEADLINE_SECONDS + 120


def test_restart_resumes_and_cannot_extend_deadline(tmp_path):
    clock = FakeClock(5_000_000)
    created_at = 5_000_000 - (DEADLINE_SECONDS - 120)  # 2 minutes of life left
    api = FakeApi(clock, pods=[{
        "id": "pod-live",
        "name": NAME,
        "createdAt": _iso(created_at),
        "status": "RUNNING",
    }])
    (tmp_path / "state.json").write_text(json.dumps({
        "attempt_id": "attempt-1",
        "pod_name": NAME,
        "image": IMAGE,
        "pod_id": "pod-live",
        "phase": "watching",
        "provider_created_at": _iso(created_at),
        "deadline_at": created_at + DEADLINE_SECONDS,
    }))

    report = make_controller(tmp_path, api, clock).run(resume=True)

    assert api.posts == 0, "a resumed controller must not create another pod"
    state = load_state(tmp_path)
    assert state["deadline_at"] == pytest.approx(created_at + DEADLINE_SECONDS)
    assert api.deletes[0][1] >= created_at + DEADLINE_SECONDS
    assert report["verified_absent"] is True


def test_restart_during_creating_phase_reconciles_by_name(tmp_path):
    clock = FakeClock(6_000_000)
    api = FakeApi(clock, pods=[{
        "id": "pod-orphan",
        "name": NAME,
        "createdAt": _iso(6_000_000 - 60),
        "status": "RUNNING",
    }])
    (tmp_path / "state.json").write_text(json.dumps({
        "attempt_id": "attempt-2",
        "pod_name": NAME,
        "image": IMAGE,
        "pod_id": None,
        "phase": "creating",
    }))

    report = make_controller(tmp_path, api, clock).run(resume=True)

    assert api.posts == 0, "reconciliation must never re-issue the create"
    assert report["pod_id"] == "pod-orphan"
    assert api.deletes[0][0] == "pod-orphan"
    assert report["verified_absent"] is True


def test_delete_failure_retries_then_reports_unresolved(tmp_path):
    clock = FakeClock(7_000_000)
    api = FakeApi(clock)
    api.delete_errors = [PodDeleteError("500"), PodDeleteError("500"), PodDeleteError("500"),
                         PodDeleteError("500"), PodDeleteError("500"), PodDeleteError("500")]

    report = make_controller(tmp_path, api, clock).run()

    assert len(api.deletes) >= 3, "deletion must be retried a bounded number of times"
    assert report["exit_code"] == UNRESOLVED_EXIT_CODE
    assert report["verified_absent"] is False
    assert load_state(tmp_path)["phase"] == "unresolved"


def test_delete_failure_followed_by_absent_inventory_is_success(tmp_path):
    clock = FakeClock(7_500_000)
    api = FakeApi(clock)
    api.delete_errors = [PodDeleteError("timeout after delete")]

    def vanish(pod_id):
        api.pods.pop(pod_id, None)
        raise PodDeleteError("timeout after delete")

    api.delete_pod = vanish

    report = make_controller(tmp_path, api, clock).run()

    assert report["verified_absent"] is True
    assert report["exit_code"] == 0


def test_pod_still_present_after_delete_is_unresolved(tmp_path):
    clock = FakeClock(7_600_000)
    api = FakeApi(clock)
    api.delete_pod = lambda pod_id: None  # accepted but ignored by the provider

    report = make_controller(tmp_path, api, clock).run()

    assert report["exit_code"] == UNRESOLVED_EXIT_CODE
    assert report["verified_absent"] is False


def test_pod_exiting_early_still_triggers_teardown(tmp_path):
    clock = FakeClock(8_000_000)
    api = FakeApi(clock)
    api.get_pod = lambda pod_id: {"id": pod_id, "name": NAME, "status": "EXITED"}

    report = make_controller(tmp_path, api, clock).run()

    assert api.deletes and api.deletes[0][0] == "pod-new-1"
    assert report["exit_code"] == 0


def test_watch_failure_still_attempts_teardown(tmp_path):
    clock = FakeClock(8_500_000)
    api = FakeApi(clock)
    api.get_error_after = 1  # inventory blips during the watch loop

    report = make_controller(tmp_path, api, clock).run()

    assert api.deletes, "teardown must run even when the watch loop raises"
    assert report["exit_code"] in (0, UNRESOLVED_EXIT_CODE)
    assert report["phase"] == "done"


# ---------------------------------------------------------------------------
# single-pod invariant
# ---------------------------------------------------------------------------


def test_refuses_to_create_a_second_pod_while_one_is_recorded(tmp_path):
    clock = FakeClock(9_000_000)
    api = FakeApi(clock, pods=[{
        "id": "pod-live",
        "name": NAME,
        "createdAt": _iso(9_000_000 - 30),
        "status": "RUNNING",
    }])
    (tmp_path / "state.json").write_text(json.dumps({
        "attempt_id": "attempt-3",
        "pod_name": NAME,
        "image": IMAGE,
        "pod_id": "pod-live",
        "phase": "watching",
        "deadline_at": 9_000_000 + DEADLINE_SECONDS,
    }))

    report = make_controller(tmp_path, api, clock).run()

    assert report["exit_code"] == REFUSED_EXIT_CODE
    assert api.posts == 0


def test_refuses_when_a_foreign_pilot_pod_already_exists(tmp_path):
    clock = FakeClock(9_500_000)
    api = FakeApi(clock, pods=[{
        "id": "pod-foreign",
        "name": NAME,
        "createdAt": _iso(9_500_000 - 10),
        "status": "RUNNING",
    }])

    report = make_controller(tmp_path, api, clock).run()

    assert report["exit_code"] == REFUSED_EXIT_CODE
    assert api.posts == 0


def test_refuses_when_any_other_pod_is_running(tmp_path):
    clock = FakeClock(9_600_000)
    api = FakeApi(clock, pods=[{
        "id": "pod-unrelated",
        "name": "some-other-pod",
        "createdAt": _iso(9_600_000 - 10),
        "status": "RUNNING",
    }])

    report = make_controller(tmp_path, api, clock).run()

    assert report["exit_code"] == REFUSED_EXIT_CODE
    assert api.posts == 0
