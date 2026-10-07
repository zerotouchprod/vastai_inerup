import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import requests

from src.worker.client import ControlPlaneClient


class FakeResponse:
    def __init__(self, status_code=204, payload=None):
        self.status_code = status_code
        self.text = ""
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses=None):
        self.headers = {}
        self.responses = list(responses or [FakeResponse()])
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json, timeout))
        return self.responses.pop(0)


class BootstrapReportingTest(unittest.TestCase):
    def test_all_client_requests_match_shared_contract_fixture(self):
        contract_path = Path(__file__).resolve().parents[2] / "contracts" / "worker-api-v1.json"
        contract = json.loads(contract_path.read_text())
        claim_request_id = "11111111-2222-4333-8444-555555555555"
        responses = [
            FakeResponse(200, {"ok": True, "retryable": False}),
            FakeResponse(200, {
                "attempt_id": "attempt-1", "job_id": "job-1", "worker_id": "worker-7",
                "provider_instance_id": "gpu-123", "gpu_lease_id": "lease-42", "boot_id": "boot-42",
                "claim_request_id": claim_request_id,
                "lease_seconds": 300, "task": {},
            }),
            FakeResponse(200, {"ok": True}),
            FakeResponse(200, {"ok": True}),
            FakeResponse(200, {"ok": True}),
        ]
        session = FakeSession(responses)
        client = ControlPlaneClient(
            "https://api.test" + contract["base_path"], "unit", "worker-7", "gpu-123",
            "lease-42", "boot-42", session=session
        )

        with patch("src.worker.client.uuid.uuid4", return_value=UUID(claim_request_id)):
            client.report_bootstrap("ready", "rev-123")
            client.claim()
            client.heartbeat("attempt-1", 0.5)
            client.complete("attempt-1", "s3://bucket/output.mp4", {"elapsed": 1.0})
            client.fail("attempt-1", "unknown")

        self.assertEqual(len(session.calls), len(contract["endpoints"]))
        for (url, payload, _timeout), (name, endpoint) in zip(session.calls, contract["endpoints"].items()):
            path = endpoint["path"].format(provider_instance_id="gpu-123", attempt_id="attempt-1")
            self.assertEqual(url, "https://api.test" + contract["base_path"] + path, name)
            self.assertEqual(endpoint["method"], "POST")
            self.assertTrue(set(endpoint["request_required"]).issubset(payload), name)
            if name in {"heartbeat", "complete", "fail"}:
                self.assertEqual(payload["claim_request_id"], claim_request_id, name)
            self.assertEqual(session.headers[contract["auth"]["header"]], "Bearer unit")

    def test_claim_request_and_response_are_bound_to_exact_lease_generation(self):
        claim_request_id = "11111111-2222-4333-8444-555555555555"
        session = FakeSession([FakeResponse(200, {
            "attempt_id": "attempt-1", "worker_id": "worker-7", "job_id": "job-1",
            "gpu_lease_id": "lease-42", "boot_id": "boot-42",
            "provider_instance_id": "gpu-123", "claim_request_id": claim_request_id,
            "lease_seconds": 300,
            "task": {"chunk_id": "chunk-1"},
        })])
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-7", "gpu-123",
            gpu_lease_id="lease-42", boot_id="boot-42", session=session
        )

        with patch("src.worker.client.uuid.uuid4", return_value=UUID(claim_request_id)):
            claim = client.claim()

        self.assertEqual(session.calls, [(
            "https://api.test/api/worker/claim",
            {
                "worker_id": "worker-7",
                "provider_instance_id": "gpu-123",
                "gpu_lease_id": "lease-42",
                "boot_id": "boot-42",
                "claim_request_id": claim_request_id,
            },
            20.0,
        )])
        self.assertEqual(claim["attempt_id"], "attempt-1")

    def test_claim_rejects_response_for_another_lease_generation(self):
        session = FakeSession([FakeResponse(200, {
            "attempt_id": "attempt-1", "worker_id": "worker-7", "job_id": "job-1",
            "gpu_lease_id": "old-lease", "boot_id": "boot-42",
            "provider_instance_id": "gpu-123", "lease_seconds": 300, "task": {},
        })])
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-7", "gpu-123",
            gpu_lease_id="lease-42", boot_id="boot-42", session=session
        )
        with self.assertRaises(ValueError):
            client.claim()

    def test_claim_rejects_response_for_another_process_on_same_lease(self):
        session = FakeSession([FakeResponse(200, {
            "attempt_id": "attempt-1", "worker_id": "worker-b", "job_id": "job-1",
            "gpu_lease_id": "lease-42", "boot_id": "boot-42",
            "provider_instance_id": "gpu-123", "lease_seconds": 300, "task": {},
        })])
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-a", "gpu-123",
            "lease-42", "boot-42", session=session
        )
        with self.assertRaises(ValueError):
            client.claim()

    def test_client_reports_worker_identity_and_image_revision(self):
        session = FakeSession()
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-7", "gpu-123", "lease-42", "boot-42", session=session
        )

        client.report_bootstrap("ready", "rev-123")

        self.assertEqual(
            session.calls,
            [
                (
                    "https://api.test/api/worker/bootstrap/gpu-123",
                    {
                        "worker_id": "worker-7",
                        "provider_instance_id": "gpu-123",
                        "gpu_lease_id": "lease-42",
                        "boot_id": "boot-42",
                        "stage": "ready",
                        "image_revision": "rev-123",
                    },
                    20.0,
                )
            ],
        )
        self.assertEqual(session.headers["Authorization"], "Bearer unit")
        self.assertNotIn("unit", repr(session.calls))

    def test_client_retries_only_transient_425(self):
        session = FakeSession([FakeResponse(425), FakeResponse()])
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-7", "gpu-123", "lease-42", "boot-42", session=session
        )

        with patch("src.worker.client.time.sleep") as sleep:
            client.report_bootstrap("started", "rev-123")

        self.assertEqual(len(session.calls), 2)
        sleep.assert_called_once_with(0.5)

    def test_client_does_not_retry_stale_lease_response(self):
        session = FakeSession([FakeResponse(409), FakeResponse()])
        client = ControlPlaneClient(
            "https://api.test/api/worker", "unit", "worker-7", "gpu-123", "lease-42", "boot-42", session=session
        )

        with patch("src.worker.client.time.sleep") as sleep:
            client.report_bootstrap("ready", "rev-123")

        self.assertEqual(len(session.calls), 1)
        sleep.assert_not_called()

    def test_main_reports_started_then_ready_before_serving(self):
        events = []
        processors = types.ModuleType("src.worker.processors")
        processors.PROCESSORS = {"pipeline": object()}
        runner = types.ModuleType("src.worker.runner")

        class FakeWorker:
            def __init__(self, client, **kwargs):
                self.client = client

            def serve(self, *args):
                events.append("serve")

        runner.Worker = FakeWorker
        previous = sys.modules.pop("src.worker.__main__", None)
        try:
            with patch.dict(
                sys.modules,
                {"src.worker.processors": processors, "src.worker.runner": runner},
            ):
                worker_main = importlib.import_module("src.worker.__main__")
        finally:
            sys.modules.pop("src.worker.__main__", None)
            if previous is not None:
                sys.modules["src.worker.__main__"] = previous

        class FakeClient:
            def __init__(self, *args):
                self.boot_id = args[4]

            def report_bootstrap(self, stage, revision):
                events.append((stage, revision, self.boot_id))

        with patch.object(worker_main, "ControlPlaneClient", FakeClient), patch.object(
            sys, "argv", ["worker", "--api", "https://api.test", "--token", "test", "--worker-id", "worker-7", "--provider-instance-id", "gpu-123", "--gpu-lease-id", "lease-42", "--boot-id", "boot-42"]
        ), patch.dict("os.environ", {"AIVIDUP_IMAGE_REVISION": "rev-123"}), patch(
            "signal.signal"
        ):
            self.assertEqual(worker_main.main(), 0)

        self.assertEqual(events[0][:2], ("started", "rev-123"))
        self.assertEqual(events[1][:2], ("ready", "rev-123"))
        self.assertEqual(events[0][2], events[1][2])
        self.assertEqual(events[2], "serve")


if __name__ == "__main__":
    unittest.main()
