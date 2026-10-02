"""HTTP client for the control-plane worker API (/api/worker/*)."""
from typing import Any, Dict, Optional

import requests


class LeaseLost(Exception):
    """The control plane no longer considers this worker the owner of the attempt (HTTP 409)."""


class ControlPlaneClient:
    def __init__(self, api_url: str, token: str, worker_id: str, timeout: float = 20.0, session=None):
        self._base = api_url.rstrip("/")
        self._worker_id = worker_id
        self._timeout = timeout
        self._http = session or requests.Session()
        self._http.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def _post(self, path: str, payload: Dict[str, Any]) -> requests.Response:
        return self._http.post(f"{self._base}{path}", json={"worker_id": self._worker_id, **payload}, timeout=self._timeout)

    def claim(self) -> Optional[Dict[str, Any]]:
        r = self._post("/claim", {})
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def heartbeat(self, attempt_id: str, progress: Optional[float] = None) -> None:
        payload = {} if progress is None else {"progress": progress}
        self._owned(self._post(f"/attempts/{attempt_id}/heartbeat", payload))

    def complete(self, attempt_id: str, output_path: str) -> None:
        self._owned(self._post(f"/attempts/{attempt_id}/complete", {"output_path": output_path}))

    def fail(self, attempt_id: str, failure_code: str) -> None:
        self._owned(self._post(f"/attempts/{attempt_id}/fail", {"failure_code": failure_code}))

    @staticmethod
    def _owned(r: requests.Response) -> None:
        if r.status_code == 409:
            raise LeaseLost(r.text)
        r.raise_for_status()
