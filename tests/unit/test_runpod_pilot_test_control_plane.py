"""Tests for the isolated single-job RunPod pilot control plane (CPU only, no production)."""

import hashlib
import json
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from scripts.runpod_pilot_test_control_plane import (
    IsolatedControlPlane,
    initialise_token,
    make_synthetic_input,
)

TOKEN = "test-token-not-a-real-secret"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def plane(tmp_path):
    source = make_synthetic_input(tmp_path / "input.mp4", seconds=2)
    instance = IsolatedControlPlane(
        token=TOKEN,
        input_path=source,
        port=free_port(),
        evidence_path=tmp_path / "evidence.json",
    )
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def identity(worker_id="w-1", provider="pod-1", lease="l-1", boot="b-1", claim=None):
    return {
        "worker_id": worker_id,
        "provider_instance_id": provider,
        "gpu_lease_id": lease,
        "boot_id": boot,
        "claim_request_id": claim or str(uuid.uuid4()),
    }


def post(url, body, token=TOKEN):
    import requests

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return requests.post(url, json=body, headers=headers, timeout=20)


# ---------------------------------------------------------------------------
# token handling
# ---------------------------------------------------------------------------


def test_token_file_is_owner_only_and_never_returned(tmp_path):
    path = tmp_path / "token"
    token = initialise_token(path)
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(token) >= 32


# ---------------------------------------------------------------------------
# auth and fail-closed routing
# ---------------------------------------------------------------------------


def test_claim_without_token_is_rejected(plane):
    response = post(f"{plane.base_url}/claim", identity(), token=None)
    assert response.status_code == 401


def test_claim_with_wrong_token_is_rejected(plane):
    response = post(f"{plane.base_url}/claim", identity(), token="nope")
    assert response.status_code == 401


def test_claim_requires_full_identity(plane):
    body = {"claim_request_id": str(uuid.uuid4())}  # no worker/lease/boot identity
    assert post(f"{plane.base_url}/claim", body).status_code == 401
    body = identity()
    body["gpu_lease_id"] = ""
    assert post(f"{plane.base_url}/claim", body).status_code == 401


def test_unknown_paths_are_not_found_and_expose_no_files(plane):
    assert post(f"{plane.base_url}/../../etc/passwd", identity()).status_code in (404, 400)
    response = post(f"{plane.base_url}/claim", identity())
    assert response.status_code == 200
    assert b"root:" not in response.content


# ---------------------------------------------------------------------------
# the single safe job
# ---------------------------------------------------------------------------


def test_job_is_not_parameterisable_from_the_network(plane):
    task = post(f"{plane.base_url}/claim", identity()).json()
    body = task["task"]
    assert body["mode"] == "interp"
    assert body["start_seconds"] == 0.0
    assert body["duration_seconds"] == pytest.approx(2.0, abs=0.4)
    assert body["input_url"].startswith(f"{plane.base_url}/input/")
    assert body["output"]["type"] == "put"
    assert body["output"]["url"].startswith(f"{plane.base_url}/sink/")
    # The job never carries an operator-supplied filesystem path or foreign URL.
    assert "path" not in body["output"]
    assert "/etc" not in json.dumps(body)


def test_job_uses_advertised_base_url_for_input_and_output_over_a_tunnel(tmp_path):
    source = make_synthetic_input(tmp_path / "input.mp4", seconds=2)
    server_port = free_port()
    advertised = "http://127.0.0.1:18099/api/worker"
    instance = IsolatedControlPlane(
        token=TOKEN,
        input_path=source,
        host="127.0.0.1",
        port=server_port,
        advertised_base_url=advertised,
    )
    instance.start()
    try:
        # The VPS-side server listener stays on server_port; only the returned URLs
        # are addressed through the Pod-side SSH-forward listener at :18099.
        assert instance.base_url == f"http://127.0.0.1:{server_port}/api/worker"
        task = post(f"{instance.base_url}/claim", identity()).json()["task"]
        assert task["input_url"].startswith(f"{advertised}/input/")
        assert task["output"]["url"].startswith(f"{advertised}/sink/")
    finally:
        instance.stop()


def test_claim_echoes_the_exact_lease_identity(plane):
    claimed = identity()
    task = post(f"{plane.base_url}/claim", claimed).json()
    for key in ("worker_id", "provider_instance_id", "gpu_lease_id", "boot_id", "claim_request_id"):
        assert task[key] == claimed[key]
    assert task["attempt_id"] and task["job_id"]
    assert task["lease_seconds"] > 0


def test_only_one_job_is_ever_served(plane):
    first = post(f"{plane.base_url}/claim", identity())
    assert first.status_code == 200
    for _ in range(3):
        assert post(f"{plane.base_url}/claim", identity()).status_code == 204
    assert plane.evidence()["claims_served"] == 1


def test_heartbeat_and_complete_for_a_foreign_attempt_are_stale(plane):
    identity()
    stray = str(uuid.uuid4())
    assert post(f"{plane.base_url}/attempts/{stray}/heartbeat", identity()).status_code == 409
    body = identity()
    body["output_path"] = "/tmp/x.mp4"
    assert post(f"{plane.base_url}/attempts/{stray}/complete", body).status_code == 409


def test_bootstrap_stages_are_recorded(plane):
    for stage in ("started", "ready"):
        body = identity()
        body.update({"stage": stage, "image_revision": "rev-1"})
        assert post(f"{plane.base_url}/bootstrap/pod-1", body).status_code == 200
    assert plane.evidence()["bootstrap_stages"] == ["started", "ready"]


def test_input_is_served_only_from_the_configured_file(plane):
    import requests

    task = post(f"{plane.base_url}/claim", identity()).json()
    response = requests.get(task["task"]["input_url"], timeout=20)
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == plane.input_sha256
    # A guessed/derived sibling path is not served.
    assert requests.get(f"{plane.base_url}/input/../evidence.json", timeout=20).status_code in (404, 400)


# ---------------------------------------------------------------------------
# result sink
# ---------------------------------------------------------------------------


def test_sink_persists_and_redacts_preflight_diagnostics(tmp_path):
    import requests

    source = make_synthetic_input(tmp_path / "input.mp4", seconds=2)
    output_dir = tmp_path / "worker-output"
    instance = IsolatedControlPlane(
        token=TOKEN,
        input_path=source,
        port=free_port(),
        evidence_path=tmp_path / "evidence.json",
        output_dir=output_dir,
    )
    instance.start()
    try:
        raw = b"CUDA_RUNTIME_PREFLIGHT_PASS token=" + TOKEN.encode() + b"\nRIFE frame probe PASS\n"
        response = requests.put(
            f"{instance.base_url}/sink/diagnostics-boot-1",
            data=raw,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain"},
            timeout=10,
        )
        assert response.status_code == 200
        evidence = instance.evidence()
        assert len(evidence["outputs"]) == 1
        saved = Path(evidence["outputs"][0]["file"])
        sanitized = b"CUDA_RUNTIME_PREFLIGHT_PASS token=[REDACTED]\nRIFE frame probe PASS\n"
        assert saved.is_file()
        assert saved.read_bytes() == sanitized
        assert saved.stat().st_mode & 0o777 == 0o600
        assert evidence["outputs"][0]["bytes"] == len(sanitized)
        assert evidence["outputs"][0]["sha256"] == hashlib.sha256(sanitized).hexdigest()
    finally:
        instance.stop()


def test_sink_requires_the_bearer_token(plane):
    import requests

    task = post(f"{plane.base_url}/claim", identity()).json()
    url = task["task"]["output"]["url"]
    assert requests.put(url, data=b"x", timeout=20).status_code == 401
    assert requests.put(url, data=b"x", headers={"Authorization": "Bearer nope"}, timeout=20).status_code == 401


def test_sink_records_received_bytes_and_hash(plane):
    import requests

    task = post(f"{plane.base_url}/claim", identity()).json()
    url = task["task"]["output"]["url"]
    payload = b"rendered-chunk-bytes"
    response = requests.put(
        url, data=payload, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=20
    )
    assert response.status_code == 200
    evidence = plane.evidence()
    assert evidence["outputs"][0]["bytes"] == len(payload)
    assert evidence["outputs"][0]["sha256"] == hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# real worker end-to-end against the isolated plane (CPU, passthrough)
# ---------------------------------------------------------------------------


def test_real_worker_completes_the_single_job(plane):
    from src.worker.client import ControlPlaneClient
    from src.worker.runner import Worker

    ids = identity()
    client = ControlPlaneClient(
        f"{plane.base_url}",
        TOKEN,
        ids["worker_id"],
        ids["provider_instance_id"],
        ids["gpu_lease_id"],
        ids["boot_id"],
    )
    client.report_bootstrap("started", "rev-test")
    worker = Worker(client, processor="passthrough")

    assert worker.run_once() is True, "the worker must claim and finish the single job"
    assert worker.run_once() is False, "no second job may ever be served"

    evidence = plane.evidence()
    assert evidence["claims_served"] == 1
    assert len(evidence["outputs"]) == 1
    assert evidence["outputs"][0]["bytes"] > 0
    assert evidence["completed"][0]["timings"], "worker timings must be captured"
    assert evidence["heartbeats"] >= 1


def test_real_worker_leaves_the_plane_idle_after_the_job(plane):
    from src.worker.client import ControlPlaneClient
    from src.worker.runner import Worker

    ids = identity()
    client = ControlPlaneClient(
        plane.base_url,
        TOKEN,
        ids["worker_id"],
        ids["provider_instance_id"],
        ids["gpu_lease_id"],
        ids["boot_id"],
    )
    worker = Worker(client, processor="passthrough")
    worker.run_once()
    assert worker.run_once() is False
    assert plane.evidence()["claims_served"] == 1


# ---------------------------------------------------------------------------
# isolation guards
# ---------------------------------------------------------------------------


def test_module_imports_no_production_clients():
    source = Path(__file__).resolve().parents[2] / "scripts" / "runpod_pilot_test_control_plane.py"
    text = source.read_text()
    for banned in ("import requests", "boto3", "psycopg", "redis", "sqlalchemy", "pymysql"):
        assert banned not in text, f"the isolated plane must not depend on {banned}"


def test_plane_binds_loopback_by_default(tmp_path):
    source = make_synthetic_input(tmp_path / "input.mp4", seconds=1)
    instance = IsolatedControlPlane(token=TOKEN, input_path=source)
    assert instance.host == "127.0.0.1"
    with pytest.raises(Exception):
        IsolatedControlPlane(token=TOKEN, input_path=source, host="0.0.0.0")
