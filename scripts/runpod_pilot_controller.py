#!/usr/bin/env python3
"""External one-shot RunPod pilot controller.

Purpose: own the entire lifetime of exactly one disposable GPU Pod from outside
it. The controller runs on a host unrelated to the Pod (it never talks to the GPU
worker, the queue, or the application) and guarantees an *absolute* deadline:
whatever happens to the Pod, the controller deletes it once
``provider_created_at + deadline_seconds`` has passed.

Guarantees:

* **Durable identity.** The intended attempt (name, image, deadline) is written to
  a state file *before* the create request, and the provider Pod id is written the
  moment it is known. A crash at any point leaves enough on disk to find and
  repossess the Pod; nothing depends on in-memory state.
* **No blind retries.** RunPod's published create schema has no idempotency key,
  so a timed-out create is *ambiguous*: the controller never re-POSTs. It
  reconciles by listing inventory and matching its unique Pod name.
* **Absolute deadline.** The clock starts at the provider's ``createdAt`` (server
  truth) and is persisted. A restart re-reads the stored deadline and never
  extends it, even if the local clock is skewed.
* **Fail-loud teardown.** Deletion is retried a bounded number of times and each
  attempt is followed by an inventory re-check. If absence cannot be *proven*,
  the controller reports UNRESOLVED and exits non-zero instead of claiming
  success.

This module intentionally contains no application, queue, or persistence code.
It only speaks the RunPod REST v2 Pod API.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

DEFAULT_BASE_URL = "https://api.runpod.io"
MAX_DELETE_ATTEMPTS = 6
RECONCILE_ATTEMPTS = 4
# Bounded grace windows. These cap the worst-case overshoot past the deadline:
# 5 x ~0.5-2s of absence checks plus ~29s of delete backoff per attempt stays
# inside a couple of minutes even when the provider refuses every delete.
DEFAULT_VERIFY_BACKOFF = (0.5, 1.0, 2.0, 2.0, 2.0)
DEFAULT_DELETE_BACKOFF = (1.0, 2.0, 3.0, 5.0, 8.0, 10.0)
DEFAULT_RECONCILE_BACKOFF = (1.0, 2.0, 4.0, 8.0)
CLEAN_EXIT_CODE = 0
UNRESOLVED_EXIT_CODE = 1
REFUSED_EXIT_CODE = 2


class PilotError(Exception):
    """A definite, non-ambiguous refusal or failure."""


class AmbiguousCreate(Exception):
    """The create request outcome is unknown: the Pod may or may not exist."""

    def __init__(self, message: str, *, pod_was_created: bool = False):
        super().__init__(message)
        self.pod_was_created = pod_was_created


class PodDeleteError(Exception):
    """A delete request failed; the Pod's existence must be verified separately."""


# ---------------------------------------------------------------------------
# RunPod REST v2 client (stdlib only)
# ---------------------------------------------------------------------------


class RunPodApi:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ):
        if not api_key:
            raise PilotError("RunPod API key is required")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _request(self, method: str, path: str, payload: Optional[dict] = None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self._key}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._base}{path}", data=data, headers=headers, method=method
        )
        return urllib.request.urlopen(request, timeout=self._timeout)

    def create_pod(self, payload: dict) -> dict:
        try:
            with self._request("POST", "/v2/pods", payload) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            body = error.read()
            status = error.code
            if status >= 500 or status == 429:
                # Server-side failure after the request was accepted: ambiguous.
                raise AmbiguousCreate(f"create returned HTTP {status}") from error
            raise PilotError(
                f"create rejected with HTTP {status}: {body[:400].decode(errors='replace')}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AmbiguousCreate(f"create transport failure: {type(error).__name__}") from error
        if status >= 300:
            raise AmbiguousCreate(f"create returned HTTP {status}")
        try:
            return json.loads(body)
        except ValueError as error:
            raise AmbiguousCreate("create returned an unreadable body") from error

    def list_pods(self) -> list[dict]:
        with self._request("GET", "/v2/pods") as response:
            body = json.loads(response.read())
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in ("pods", "items", "data"):
                value = body.get(key)
                if isinstance(value, list):
                    return value
        raise PilotError("unexpected pod inventory payload")

    def get_pod(self, pod_id: str) -> Optional[dict]:
        try:
            with self._request("GET", f"/v2/pods/{urllib.parse.quote(pod_id, safe='')}") as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def delete_pod(self, pod_id: str) -> None:
        try:
            with self._request("DELETE", f"/v2/pods/{urllib.parse.quote(pod_id, safe='')}") as response:
                response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return  # already gone
            raise PodDeleteError(f"delete returned HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise PodDeleteError(f"delete transport failure: {type(error).__name__}") from error


# ---------------------------------------------------------------------------
# Durable state
# ---------------------------------------------------------------------------


class StateStore:
    """Atomic, owner-only JSON state so a restart can always repossess the Pod."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> Optional[dict]:
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return None
        try:
            value = json.loads(raw)
        except ValueError as error:
            raise PilotError(f"state file {self.path} is unreadable") from error
        if not isinstance(value, dict):
            raise PilotError(f"state file {self.path} is not an object")
        return value

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + f".tmp-{os.getpid()}")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_provider_time(value: Any) -> Optional[float]:
    """Parse the provider's timestamp into an epoch; tolerate trailing 'Z'."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.timestamp()


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class PilotController:
    def __init__(
        self,
        api: Any,
        state_path: Path,
        pod_name: str,
        image: str,
        *,
        deadline_seconds: int = 1800,
        poll_seconds: float = 30.0,
        gpu_id: Optional[str] = None,
        data_centre: Optional[str] = None,
        pod_disk_gb: int = 20,
        env: Optional[dict] = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        logger: Callable[[str], None] = lambda message: print(message, flush=True),
        verify_backoff: Iterable[float] = DEFAULT_VERIFY_BACKOFF,
        delete_backoff: Iterable[float] = DEFAULT_DELETE_BACKOFF,
        reconcile_backoff: Iterable[float] = DEFAULT_RECONCILE_BACKOFF,
    ):
        if isinstance(deadline_seconds, bool) or not isinstance(deadline_seconds, (int, float)):
            raise PilotError("deadline_seconds must be a number")
        if not deadline_seconds > 0:
            raise PilotError("deadline_seconds must be positive")
        if not pod_name or not image:
            raise PilotError("pod_name and image are required")
        self._api = api
        self._store = StateStore(state_path)
        self._pod_name = pod_name
        self._image = image
        # Kept as a float: truncating here would silently collapse a short
        # deadline to zero and delete the pod immediately.
        self._deadline_seconds = float(deadline_seconds)
        self._poll = max(0.1, float(poll_seconds))
        self._gpu_id = gpu_id
        self._data_centre = data_centre
        self._disk = pod_disk_gb
        self._env = dict(env or {})
        self._clock = clock
        self._sleep = sleeper
        self._log = logger
        # Bounded grace windows keep worst-case overshoot past the deadline small.
        self._verify_backoff = tuple(verify_backoff)
        self._delete_backoff = tuple(delete_backoff)
        self._reconcile_backoff = tuple(reconcile_backoff)
        if not self._verify_backoff or not self._delete_backoff or not self._reconcile_backoff:
            raise PilotError("backoff sequences must be non-empty")

    # -- payload -------------------------------------------------------
    def build_payload(self) -> dict:
        payload: dict[str, Any] = {
            "name": self._pod_name,
            "cloud": "SECURE",
            "image": self._image,
            "disk": self._disk,
            "env": dict(self._env),
        }
        if self._gpu_id:
            payload["gpu"] = {"id": self._gpu_id, "count": 1}
        if self._data_centre:
            payload["dataCenterIds"] = [self._data_centre]
        return payload

    # -- inventory helpers --------------------------------------------
    def _inventory(self) -> list[dict]:
        pods = self._api.list_pods()
        if not isinstance(pods, list):
            raise PilotError("pod inventory is not a list")
        return pods

    def _find_by_name(self, pods: Iterable[dict]) -> Optional[dict]:
        for pod in pods:
            if isinstance(pod, dict) and pod.get("name") == self._pod_name:
                return pod
        return None

    def _verify_absent(self, pod_id: str) -> bool:
        """Prove the Pod is gone by re-reading inventory, never by assuming."""
        last_error: Optional[Exception] = None
        for attempt, delay in enumerate(self._verify_backoff):
            try:
                pods = self._inventory()
            except Exception as error:  # noqa: BLE001 - inventory must be proven
                last_error = error
            else:
                if pod_id not in {str(p.get("id")) for p in pods if isinstance(p, dict)}:
                    return True
            if attempt < len(self._verify_backoff) - 1:
                self._sleep(delay)
        if last_error is not None:
            self._log(f"inventory verification failed: {type(last_error).__name__}: {last_error}")
        return False

    # -- phases --------------------------------------------------------
    def _preflight_inventory(self) -> Optional[str]:
        """Refuse to start when any other Pod exists (single-Pod discipline)."""
        try:
            pods = self._inventory()
        except Exception as error:  # noqa: BLE001
            return f"cannot read pod inventory: {type(error).__name__}: {error}"
        live = [
            p
            for p in pods
            if isinstance(p, dict) and str(p.get("status", "")).upper() not in {"TERMINATED"}
        ]
        if not live:
            return None
        names = ", ".join(f"{p.get('name')}({p.get('id')})" for p in live[:5])
        return f"refusing to run while {len(live)} pod(s) exist: {names}"

    def _adopt(self, state: dict, pod: dict) -> None:
        pod_id = str(pod.get("id"))
        created = parse_provider_time(pod.get("createdAt")) or parse_provider_time(
            pod.get("created_at")
        )
        if created is None:
            # No provider truth available: fall back to the durable local record.
            created = state.get("_create_requested_epoch") or self._clock()
        state["pod_id"] = pod_id
        state["provider_created_at"] = _iso(created)
        state["deadline_at"] = created + self._deadline_seconds
        state["phase"] = "watching"

    def _reconcile_after_ambiguous_create(self, state: dict) -> Optional[dict]:
        """Find the Pod our create may have produced, by our unique name only."""
        for attempt, delay in enumerate(self._reconcile_backoff):
            pods = self._inventory()
            found = self._find_by_name(pods)
            if found is not None:
                return found
            if attempt < len(self._reconcile_backoff) - 1:
                self._sleep(delay)
        return None

    def _create(self, state: dict) -> None:
        state["_create_requested_epoch"] = self._clock()
        state["create_requested_at"] = _utc_now_iso()
        state["phase"] = "creating"
        self._store.save(state)  # durable intent BEFORE the request
        self._log(f"creating one pod name={self._pod_name} image={self._image}")
        try:
            pod = self._api.create_pod(self.build_payload())
        except AmbiguousCreate as error:
            self._log(f"create is ambiguous ({error}); reconciling by name, never re-POSTing")
            try:
                found = self._reconcile_after_ambiguous_create(state)
            except Exception as reconcile_error:  # noqa: BLE001
                # The create outcome is unknown and we cannot even read inventory:
                # report UNRESOLVED so a human checks the provider console.
                state["phase"] = "unresolved"
                state["notes"] = [
                    *state.get("notes", []),
                    f"ambiguous create and unreadable inventory: {reconcile_error}",
                ]
                self._store.save(state)
                self._log(
                    "create outcome unknown and inventory unreadable; "
                    "check the provider console for a stray pod"
                )
                return
            if found is None:
                self._log("no pod with our name exists; treating the create as not created")
                state["phase"] = "no_pod"
                state["pod_id"] = None
                self._store.save(state)
                return
            self._adopt(state, found)
            self._store.save(state)
            return
        if not isinstance(pod, dict) or not pod.get("id"):
            raise PilotError("create returned no pod id")
        self._adopt(state, pod)
        self._store.save(state)

    def _watch(self, state: dict) -> None:
        pod_id = state["pod_id"]
        deadline = float(state["deadline_at"])
        inventory_errors = 0
        while True:
            now = self._clock()
            remaining = deadline - now
            if remaining <= 0:
                self._log(f"deadline reached for pod {pod_id}")
                return
            try:
                pod = self._api.get_pod(pod_id)
            except Exception as error:  # noqa: BLE001 - transient inventory blips
                inventory_errors += 1
                self._log(f"pod lookup failed ({type(error).__name__}); will retry")
                if inventory_errors >= 10:
                    self._log("pod lookup failing repeatedly; enforcing deadline only")
                    self._sleep(remaining)
                    return
                self._sleep(min(self._poll, remaining))
                continue
            if pod is None:
                self._log(f"pod {pod_id} already absent")
                return
            status = str(pod.get("status", "")).upper()
            if status in {"EXITED", "TERMINATED", "STOPPED"}:
                self._log(f"pod {pod_id} is {status}; tearing down now")
                return
            self._sleep(min(self._poll, remaining))

    def _teardown(self, state: dict) -> bool:
        pod_id = str(state["pod_id"])
        deleted = False
        attempts = len(self._delete_backoff)
        for attempt in range(1, attempts + 1):
            try:
                self._api.delete_pod(pod_id)
                deleted = True
            except Exception as error:  # noqa: BLE001 - verify rather than trust
                self._log(f"delete attempt {attempt} failed: {type(error).__name__}: {error}")
            # A failed delete may still have succeeded: always re-check inventory.
            if self._verify_absent(pod_id):
                state["phase"] = "done"
                state["verified_absent"] = True
                state["delete_attempts"] = attempt
                state["deleted"] = deleted
                self._store.save(state)
                self._log(f"pod {pod_id} verified absent after {attempt} delete attempt(s)")
                return True
            if attempt < attempts:
                self._sleep(self._delete_backoff[attempt - 1])
        state["phase"] = "unresolved"
        state["verified_absent"] = False
        state["delete_attempts"] = attempts
        self._store.save(state)
        self._log(
            f"UNRESOLVED: pod {pod_id} could not be proven absent after "
            f"{attempts} attempts - terminate it manually"
        )
        return False

    # -- entry point ----------------------------------------------------
    def _report(self, state: Optional[dict], *, verified_absent: bool, exit_code: int, **extra) -> dict:
        report: dict[str, Any] = {
            "attempt_id": (state or {}).get("attempt_id"),
            "pod_name": self._pod_name,
            "pod_id": (state or {}).get("pod_id"),
            "image": self._image,
            "phase": (state or {}).get("phase"),
            "deadline_at": (state or {}).get("deadline_at"),
            "verified_absent": bool(verified_absent),
            "exit_code": exit_code,
        }
        report.update(extra)
        return report

    def run(self, resume: bool = False) -> dict:
        state = self._store.load()
        if state is not None and not resume:
            pod_id = state.get("pod_id")
            if pod_id and state.get("phase") in {"creating", "watching"}:
                reason = (
                    f"state records live pod {pod_id}; rerun with --resume to repossess it"
                )
            elif not pod_id and state.get("phase") == "creating":
                reason = "state records an in-flight create; rerun with --resume to reconcile it"
            else:
                reason = None
            if reason:
                self._log(f"refusing: {reason}")
                return self._report(state, verified_absent=False, exit_code=REFUSED_EXIT_CODE, refused=reason)
        if state is None and resume:
            reason = "no state file to resume from"
            self._log(f"refusing: {reason}")
            return self._report(None, verified_absent=False, exit_code=REFUSED_EXIT_CODE, refused=reason)

        if state is None:
            try:
                refuse = self._preflight_inventory()
            except Exception as error:  # noqa: BLE001
                refuse = f"cannot read pod inventory: {type(error).__name__}: {error}"
            if refuse:
                self._log(f"refusing: {refuse}")
                return self._report(None, verified_absent=False, exit_code=REFUSED_EXIT_CODE, refused=refuse)
            state = {
                "attempt_id": os.urandom(8).hex(),
                "pod_name": self._pod_name,
                "image": self._image,
                "pod_id": None,
                "phase": "creating",
                "deadline_seconds": self._deadline_seconds,
            }
            self._create(state)
            if state.get("phase") == "unresolved":
                return self._report(state, verified_absent=False, exit_code=UNRESOLVED_EXIT_CODE)
            if state.get("phase") == "no_pod":
                state.pop("_create_requested_epoch", None)
                self._store.save(state)
                return self._report(state, verified_absent=True, exit_code=CLEAN_EXIT_CODE)

        # Recompute the deadline without ever extending it.
        if state.get("pod_id"):
            deadline = state.get("deadline_at")
            if deadline is None:
                created = parse_provider_time(state.get("provider_created_at"))
                if created is None:
                    created = state.get("_create_requested_epoch")
                if created is None:
                    reason = "cannot determine the pod deadline from state; refusing to guess"
                    self._log(f"refusing: {reason}")
                    return self._report(
                        state, verified_absent=False, exit_code=REFUSED_EXIT_CODE, refused=reason
                    )
                deadline = created + self._deadline_seconds
                state["deadline_at"] = deadline
            if state.get("phase") == "creating":
                state["phase"] = "watching"
            self._store.save(state)

        if not state.get("pod_id") and state.get("phase") == "creating":
            try:
                found = self._reconcile_after_ambiguous_create(state)
            except Exception as error:  # noqa: BLE001
                state["phase"] = "unresolved"
                self._store.save(state)
                return self._report(state, verified_absent=False, exit_code=UNRESOLVED_EXIT_CODE)
            if found is None:
                state["phase"] = "no_pod"
                self._store.save(state)
            else:
                # A previous run's create did land: repossess it instead of
                # creating a second Pod.
                self._adopt(state, found)
                self._store.save(state)

        verified_absent = True
        if state.get("pod_id"):
            try:
                self._watch(state)
            except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001
                # Teardown must happen even if watching failed or the operator
                # interrupted: that is the entire point of an external controller.
                self._log(f"watch loop stopped ({type(error).__name__}); enforcing teardown")
            finally:
                self._store.save(state)
            verified_absent = self._teardown(state)

        state.pop("_create_requested_epoch", None)
        self._store.save(state)
        unresolved = state.get("phase") == "unresolved" or not verified_absent
        return self._report(
            state,
            verified_absent=verified_absent,
            exit_code=UNRESOLVED_EXIT_CODE if unresolved else CLEAN_EXIT_CODE,
        )


def _iso(epoch: float) -> str:
    return (
        _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]
        + "Z"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_api_key(args: argparse.Namespace) -> str:
    if os.environ.get("RUNPOD_API_KEY"):
        return os.environ["RUNPOD_API_KEY"]
    if args.api_key_file:
        for line in Path(args.api_key_file).read_text().splitlines():
            line = line.strip()
            if line.startswith("RUNPOD_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise PilotError("no API key: set RUNPOD_API_KEY or pass --api-key-file")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--gpu", default=os.environ.get("PILOT_GPU_ID"))
    parser.add_argument("--data-centre", default=os.environ.get("PILOT_DATA_CENTRE"))
    parser.add_argument("--disk-gb", type=int, default=20)
    parser.add_argument("--deadline-seconds", type=int, default=1800)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the payload and exit")
    parser.add_argument("--api-key-file", default="/home/informaten/runpod.env")
    args = parser.parse_args(argv)

    env = {
        "AIVIDUP_IDLE_EXIT_SECONDS": "1800",
        "AIVIDUP_MAX_LIFETIME_SECONDS": "1800",
        "AIVIDUP_MAX_RESTARTS": "0",
        "AIVIDUP_MODEL_MANIFEST_REQUIRED": "1",
    }
    try:
        if args.dry_run:
            controller = PilotController(
                api=None,
                state_path=args.state_file,
                pod_name=args.pod_name,
                image=args.image,
                deadline_seconds=args.deadline_seconds,
                gpu_id=args.gpu,
                data_centre=args.data_centre,
                pod_disk_gb=args.disk_gb,
                env=env,
            )
            print(json.dumps(controller.build_payload(), indent=2, sort_keys=True))
            return CLEAN_EXIT_CODE
        controller = PilotController(
            api=RunPodApi(load_api_key(args)),
            state_path=args.state_file,
            pod_name=args.pod_name,
            image=args.image,
            deadline_seconds=args.deadline_seconds,
            poll_seconds=args.poll_seconds,
            gpu_id=args.gpu,
            data_centre=args.data_centre,
            pod_disk_gb=args.disk_gb,
            env=env,
        )
        report = controller.run(resume=args.resume)
    except PilotError as error:
        print(json.dumps({"exit_code": REFUSED_EXIT_CODE, "refused": str(error)}, sort_keys=True))
        return REFUSED_EXIT_CODE
    except KeyboardInterrupt:
        print(json.dumps({"exit_code": UNRESOLVED_EXIT_CODE, "interrupted": True}, sort_keys=True))
        return UNRESOLVED_EXIT_CODE
    print(json.dumps(report, sort_keys=True))
    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
