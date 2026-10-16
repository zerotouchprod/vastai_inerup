"""Transport-level tests: the real RunPodApi REST v2 client driven by a local impersonator."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.runpod_pilot_controller import (
    AmbiguousCreate,
    PilotController,
    PilotError,
    PodDeleteError,
    RunPodApi,
)

IMAGE = "ghcr.io/zerotouchprod/aividup-worker-runpod-rife-pilot@sha256:" + "c" * 64
NAME = "aividup-rife-pilot-http"
# Test-speed backoffs: real values are bounded but would make this suite slow.
FAST_BACKOFFS = dict(
    verify_backoff=(0.0, 0.0),
    delete_backoff=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    reconcile_backoff=(0.0, 0.0),
)


def _now_iso() -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )


class Impersonator(BaseHTTPRequestHandler):
    """Minimal RunPod REST v2 Pod API stand-in with switchable failure modes."""

    scenario = {}
    calls = []
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        return

    def _json(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth_ok(self):
        return str(self.headers.get("Authorization", "")).startswith("Bearer ")

    def do_GET(self):
        type(self).calls.append(("GET", self.path))
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        scenario = type(self).scenario
        if self.path == "/v2/pods":
            if scenario.get("inventory_status") == 500:
                self._send(500, {"error": "boom"})
                return
            if scenario.get("inventory_bare_list"):
                self._send(200, list(scenario.get("pods", {}).values()))
                return
            self._send(200, {"pods": list(scenario.get("pods", {}).values())})
            return
        pod_id = self.path.rsplit("/", 1)[-1]
        pods = scenario.get("pods", {})
        if pod_id in pods:
            self._send(200, pods[pod_id])
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        type(self).calls.append(("POST", self.path))
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        scenario = type(self).scenario
        payload = self._json()
        mode = scenario.get("create", "ok")
        if mode == "server_error":
            if scenario.get("create_lands"):
                scenario.setdefault("pods", {})["pod-http-1"] = {
                    "id": "pod-http-1",
                    "name": payload["name"],
                    "createdAt": "2026-10-16T05:00:00.000Z",
                    "status": "RUNNING",
                }
            self._send(500, {"error": "internal"})
            return
        if mode == "rejected":
            self._send(422, {"error": "invalid gpu"})
            return
        pod = {
            "id": "pod-http-1",
            "name": payload["name"],
            "createdAt": scenario.get("created_at") or _now_iso(),
            "status": "RUNNING",
        }
        scenario.setdefault("pods", {})["pod-http-1"] = pod
        self._send(201, pod)

    def do_DELETE(self):
        type(self).calls.append(("DELETE", self.path))
        if not self._auth_ok():
            self._send(401, {"error": "unauthorized"})
            return
        scenario = type(self).scenario
        pod_id = self.path.rsplit("/", 1)[-1]
        status = scenario.get("delete_status", 200)
        if scenario.get("delete_deletes"):
            scenario.setdefault("pods", {}).pop(pod_id, None)
        if status == 404:
            self._send(404, {"error": "not found"})
            return
        if status != 200:
            self._send(status, {"error": "delete failed"})
            return
        if not scenario.get("delete_leaves_pod"):
            scenario.setdefault("pods", {}).pop(pod_id, None)
        self._send(200, {"deleted": True})


@pytest.fixture
def provider():
    Impersonator.scenario = {}
    Impersonator.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Impersonator)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def build(tmp_path, provider, **over):
    kwargs = dict(
        api=RunPodApi("test-key", base_url=provider, timeout=10),
        state_path=tmp_path / "state.json",
        pod_name=NAME,
        image=IMAGE,
        deadline_seconds=over.pop("deadline_seconds", 1),
        poll_seconds=0.05,
        gpu_id="NVIDIA GeForce RTX 3090",
        data_centre="EU-CZ-1",
        sleeper=time.sleep,
    )
    kwargs.update(FAST_BACKOFFS)
    kwargs.update(over)
    return PilotController(**kwargs)


def state(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


# ---------------------------------------------------------------------------
# client contract against the real HTTP surface
# ---------------------------------------------------------------------------


def test_client_reads_the_documented_inventory_envelope(provider):
    Impersonator.scenario["pods"] = {"pod-a": {"id": "pod-a", "name": "n", "status": "RUNNING"}}
    assert [p["id"] for p in RunPodApi("k", base_url=provider).list_pods()] == ["pod-a"]
    Impersonator.scenario["inventory_bare_list"] = True
    assert [p["id"] for p in RunPodApi("k", base_url=provider).list_pods()] == ["pod-a"]


def test_client_maps_500_create_to_ambiguous(provider):
    Impersonator.scenario["create"] = "server_error"
    with pytest.raises(AmbiguousCreate):
        RunPodApi("k", base_url=provider).create_pod({"name": NAME, "image": IMAGE})


def test_client_maps_422_create_to_a_definite_refusal(provider):
    Impersonator.scenario["create"] = "rejected"
    with pytest.raises(PilotError):
        RunPodApi("k", base_url=provider).create_pod({"name": NAME, "image": IMAGE})


def test_client_treats_404_delete_as_already_gone(provider):
    RunPodApi("k", base_url=provider).delete_pod("missing")  # must not raise


def test_client_sends_a_bearer_token(provider):
    with pytest.raises(PilotError):
        RunPodApi("", base_url=provider).list_pods()
    RunPodApi("k", base_url=provider).list_pods()
    assert Impersonator.calls


# ---------------------------------------------------------------------------
# full controller over real HTTP
# ---------------------------------------------------------------------------


def test_controller_creates_watches_and_deletes_over_http(tmp_path, provider):
    report = build(tmp_path, provider).run()
    verbs = [verb for verb, _ in Impersonator.calls]
    assert verbs[0] == "GET", "inventory must be read before creating"
    assert "POST" in verbs and "DELETE" in verbs
    assert report["verified_absent"] is True
    assert report["exit_code"] == 0
    assert state(tmp_path)["pod_id"] == "pod-http-1"


def test_controller_recovers_a_pod_created_by_an_ambiguous_http_create(tmp_path, provider):
    Impersonator.scenario.update({"create": "server_error", "create_lands": True})

    report = build(tmp_path, provider).run()

    posts = [c for c in Impersonator.calls if c[0] == "POST"]
    assert len(posts) == 1, "the controller must not re-POST an ambiguous create"
    assert report["pod_id"] == "pod-http-1"
    assert report["verified_absent"] is True


def test_controller_reports_unresolved_when_http_delete_fails(tmp_path, provider):
    Impersonator.scenario.update({"delete_status": 500})

    report = build(tmp_path, provider, deadline_seconds=0.2).run()

    assert report["exit_code"] == 1
    assert report["verified_absent"] is False
    assert state(tmp_path)["phase"] == "unresolved"


def test_controller_succeeds_when_http_delete_fails_but_pod_is_gone(tmp_path, provider):
    # A 500 whose effect actually landed: inventory is the source of truth.
    Impersonator.scenario.update({"delete_status": 500, "delete_deletes": True})

    report = build(tmp_path, provider, deadline_seconds=0.2).run()

    assert report["verified_absent"] is True


def test_controller_deletes_at_the_deadline_over_http(tmp_path, provider):
    started = time.monotonic()
    report = build(tmp_path, provider, deadline_seconds=0.5).run()
    elapsed = time.monotonic() - started
    assert report["exit_code"] == 0
    assert elapsed >= 0.5, "the pod must not be deleted before its deadline"
    delete_times = [c for c in Impersonator.calls if c[0] == "DELETE"]
    assert delete_times


def test_controller_refuses_over_http_when_a_pod_already_exists(tmp_path, provider):
    Impersonator.scenario["pods"] = {
        "pod-other": {"id": "pod-other", "name": "unrelated", "status": "RUNNING"}
    }

    report = build(tmp_path, provider).run()

    assert report["exit_code"] == 2
    assert all(c[0] != "POST" for c in Impersonator.calls)


def test_api_key_is_never_sent_without_bearer_scheme(provider):
    RunPodApi("k", base_url=provider).list_pods()
    assert Impersonator.calls
