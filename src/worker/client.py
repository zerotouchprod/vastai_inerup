"""HTTP client for the control-plane worker API (/api/worker/*)."""

from typing import Any, Dict, Optional

import logging
import time
import uuid
from urllib.parse import quote

import requests


class LeaseLost(Exception):
    """The control plane no longer considers this worker the owner of the attempt (HTTP 409)."""


class ControlPlaneClient:
    def __init__(
        self,
        api_url: str,
        token: str,
        worker_id: str,
        provider_instance_id: str,
        gpu_lease_id: str,
        boot_id: str,
        timeout: float = 20.0,
        session=None,
    ):
        self._base = api_url.rstrip("/")
        if not worker_id or not provider_instance_id or not gpu_lease_id or not boot_id:
            raise ValueError(
                "worker, provider instance, GPU lease, and boot identities are required"
            )
        self._worker_id = worker_id
        self._provider_instance_id = provider_instance_id
        self._gpu_lease_id = gpu_lease_id
        self._boot_id = boot_id
        self._timeout = timeout
        self._claim_request_ids: Dict[str, str] = {}
        self._http = session or requests.Session()
        self._http.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )

    def _post(self, path: str, payload: Dict[str, Any]) -> requests.Response:
        return self._http.post(
            f"{self._base}{path}",
            json={
                **payload,
                "worker_id": self._worker_id,
                "provider_instance_id": self._provider_instance_id,
                "gpu_lease_id": self._gpu_lease_id,
                "boot_id": self._boot_id,
            },
            timeout=self._timeout,
        )

    def claim(self) -> Optional[Dict[str, Any]]:
        claim_request_id = str(uuid.uuid4())
        r = self._post("/claim", {"claim_request_id": claim_request_id})
        if r.status_code == 204:
            return None
        r.raise_for_status()
        task = r.json()
        if not isinstance(task, dict) or any(
            task.get(key) != expected
            for key, expected in (
                ("worker_id", self._worker_id),
                ("provider_instance_id", self._provider_instance_id),
                ("gpu_lease_id", self._gpu_lease_id),
                ("boot_id", self._boot_id),
                ("claim_request_id", claim_request_id),
            )
        ):
            raise ValueError(
                "Control plane returned a task for a different worker lease generation or claim"
            )
        if not isinstance(task.get("attempt_id"), str) or not task["attempt_id"]:
            raise ValueError("Control plane returned a claim without an attempt id")
        if not isinstance(task.get("job_id"), str) or not task["job_id"]:
            raise ValueError("Control plane returned a claim without a job id")
        if not isinstance(task.get("task"), dict):
            raise ValueError("Control plane returned an invalid task payload")
        self._claim_request_ids[task["attempt_id"]] = claim_request_id
        return task

    def _claim_request_id(self, attempt_id: str) -> str:
        try:
            return self._claim_request_ids[attempt_id]
        except KeyError as exc:
            raise LeaseLost(
                "No successful claim identity is stored for this attempt"
            ) from exc

    def heartbeat(self, attempt_id: str, progress: Optional[float] = None) -> None:
        payload: Dict[str, Any] = {
            "claim_request_id": self._claim_request_id(attempt_id)
        }
        if progress is not None:
            payload["progress"] = progress
        self._owned(self._post(f"/attempts/{attempt_id}/heartbeat", payload))

    def complete(
        self,
        attempt_id: str,
        output_path: str,
        timings: Optional[Dict[str, float]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "output_path": output_path,
            "claim_request_id": self._claim_request_id(attempt_id),
        }
        if timings:
            payload["timings"] = timings
        self._owned(self._post(f"/attempts/{attempt_id}/complete", payload))

    def fail(self, attempt_id: str, failure_code: str) -> None:
        self._owned(
            self._post(
                f"/attempts/{attempt_id}/fail",
                {
                    "failure_code": failure_code,
                    "claim_request_id": self._claim_request_id(attempt_id),
                },
            )
        )

    def report_bootstrap(self, stage: str, image_revision: str) -> None:
        """Report startup milestones using the orchestration-assigned lease generation."""
        if stage not in {"started", "ready"}:
            raise ValueError(f"Unsupported bootstrap stage: {stage}")

        for attempt in range(5):
            try:
                response = self._post(
                    f"/bootstrap/{quote(self._provider_instance_id, safe='')}",
                    {
                        "stage": stage,
                        "image_revision": image_revision,
                        "boot_id": self._boot_id,
                    },
                )
                if response.status_code == 425:
                    if attempt < 4:
                        time.sleep(min(0.5 * (2**attempt), 4.0))
                    continue
                response.raise_for_status()
                return
            except requests.RequestException as exc:
                logging.getLogger(__name__).warning(
                    "Bootstrap %s report failed (%s)", stage, type(exc).__name__
                )
                return

        logging.getLogger(__name__).warning(
            "Bootstrap %s report still unavailable after bounded retries", stage
        )

    @staticmethod
    def _owned(r: requests.Response) -> None:
        if r.status_code == 409:
            raise LeaseLost(r.text)
        r.raise_for_status()
