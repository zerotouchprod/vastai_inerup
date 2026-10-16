"""Fail-closed registry for Vast machine certifications."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class PoolEnvironment:
    worker_digest: str
    cuda_version: str
    pytorch_version: str


@dataclass
class MachineRecord:
    machine_id: int
    status: str
    last_result: str
    worker_digest: str
    cuda_version: str
    pytorch_version: str
    gpu_model: str
    last_pass_at: str | None
    evidence_ref: str
    cleanup_confirmed: bool
    notes: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MachineRecord":
        return cls(**value)

    def is_compatible(self, environment: PoolEnvironment) -> bool:
        return (
            self.status == "verified"
            and self.cleanup_confirmed
            and self.worker_digest == environment.worker_digest
            and self.cuda_version == environment.cuda_version
            and self.pytorch_version == environment.pytorch_version
            and bool(self.last_pass_at)
            and bool(self.evidence_ref)
        )


class MachinePool:
    def __init__(self, records: Iterable[dict[str, Any] | MachineRecord]):
        self._records: dict[int, MachineRecord] = {}
        for record in records:
            item = (
                record
                if isinstance(record, MachineRecord)
                else MachineRecord.from_dict(record)
            )
            self._records[item.machine_id] = item

    def machine(self, machine_id: int) -> MachineRecord:
        return self._records[machine_id]

    def allowed_machine_ids(self, environment: PoolEnvironment) -> list[int]:
        """Return only environment-compatible verified machines; never fallback."""
        return sorted(
            machine_id
            for machine_id, record in self._records.items()
            if record.is_compatible(environment)
        )

    def filter_offers(
        self, offers: Iterable[dict[str, Any]], environment: PoolEnvironment
    ) -> list[dict[str, Any]]:
        allowed = set(self.allowed_machine_ids(environment))
        return [offer for offer in offers if offer.get("machine_id") in allowed]

    def allows_offer(self, offer: dict[str, Any], environment: PoolEnvironment) -> bool:
        return bool(self.filter_offers([offer], environment))

    def record_probe(self, **fields: Any) -> MachineRecord:
        machine = MachineRecord.from_dict(fields)
        if machine.status == "verified" and (
            machine.last_result != "PASS"
            or not machine.cleanup_confirmed
            or not machine.last_pass_at
        ):
            raise ValueError(
                "verified requires PASS, cleanup_confirmed, and last_pass_at"
            )
        self._records[machine.machine_id] = machine
        return machine

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "pool": [record.__dict__ for record in self._records.values()],
        }


def load_machine_pool(path: str | Path) -> MachinePool:
    document = json.loads(Path(path).read_text())
    if document.get("version") != 1:
        raise ValueError("unsupported machine pool version")
    return MachinePool(document.get("pool", []))
