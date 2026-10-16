from pathlib import Path
import os

from src.infrastructure.vastai.verified_machine_pool import (
    MachinePool,
    PoolEnvironment,
    load_machine_pool,
)

POOL_PATH = Path(
    os.environ.get(
        "VAST_POOL_PATH",
        Path(__file__).parents[1] / "config" / "vast_verified_machine_pool.json",
    )
)


def test_failed_machine_is_cooldown_with_environment_fingerprint():
    pool = load_machine_pool(POOL_PATH)
    record = pool.machine(18551)

    assert record.status == "cooldown"
    assert record.last_result == "STARTUP_TIMEOUT"
    assert record.worker_digest.startswith("sha256:")
    assert record.cuda_version == "12.6"
    assert record.pytorch_version == "2.9.1+cu126"
    assert record.evidence_ref.endswith("56224313")


def test_production_returns_only_verified_environment_compatible_machines():
    pool = MachinePool(
        [
            {
                "machine_id": 10,
                "status": "verified",
                "worker_digest": "sha256:good",
                "cuda_version": "12.6",
                "pytorch_version": "2.9.1+cu126",
                "gpu_model": "RTX A4000",
                "last_result": "PASS",
                "last_pass_at": "2026-10-16T00:00:00Z",
                "cleanup_confirmed": True,
                "evidence_ref": "evidence/10",
            },
            {
                "machine_id": 11,
                "status": "verified",
                "worker_digest": "sha256:stale",
                "cuda_version": "12.5",
                "pytorch_version": "2.9.1+cu126",
                "gpu_model": "RTX A4000",
                "last_result": "PASS",
                "last_pass_at": "2026-10-16T00:00:00Z",
                "cleanup_confirmed": True,
                "evidence_ref": "evidence/11",
            },
            {
                "machine_id": 12,
                "status": "cooldown",
                "worker_digest": "sha256:bad",
                "cuda_version": "12.6",
                "pytorch_version": "2.9.1+cu126",
                "gpu_model": "RTX A4000",
                "last_result": "STARTUP_TIMEOUT",
                "last_pass_at": None,
                "cleanup_confirmed": True,
                "evidence_ref": "evidence/12",
            },
        ]
    )

    assert pool.allowed_machine_ids(
        PoolEnvironment("sha256:good", "12.6", "2.9.1+cu126")
    ) == [10]
    assert (
        pool.allowed_machine_ids(
            PoolEnvironment("sha256:missing", "12.6", "2.9.1+cu126")
        )
        == []
    )


def test_filter_offers_uses_machine_id_not_offer_or_instance_id():
    pool = MachinePool(
        [
            {
                "machine_id": 42,
                "status": "verified",
                "last_result": "PASS",
                "worker_digest": "sha256:good",
                "cuda_version": "12.6",
                "pytorch_version": "2.9.1+cu126",
                "gpu_model": "RTX A4000",
                "last_pass_at": "2026-10-16T00:00:00Z",
                "evidence_ref": "evidence/42",
                "cleanup_confirmed": True,
            }
        ]
    )
    offers = [
        {"id": 1001, "instance_id": 9001, "machine_id": 42},
        {"id": 1002, "instance_id": 9002, "machine_id": 99},
    ]

    assert pool.filter_offers(
        offers, PoolEnvironment("sha256:good", "12.6", "2.9.1+cu126")
    ) == [offers[0]]

    pool = MachinePool([])

    pool.record_probe(
        machine_id=20,
        status="cooldown",
        last_result="STARTUP_TIMEOUT",
        worker_digest="sha256:x",
        cuda_version="12.6",
        pytorch_version="2.9.1+cu126",
        gpu_model="RTX A4000",
        last_pass_at=None,
        evidence_ref="evidence/20",
        cleanup_confirmed=True,
    )
    assert pool.machine(20).status == "cooldown"

    pool.record_probe(
        machine_id=20,
        status="verified",
        last_result="PASS",
        worker_digest="sha256:x",
        cuda_version="12.6",
        pytorch_version="2.9.1+cu126",
        gpu_model="RTX A4000",
        last_pass_at="2026-10-16T00:00:00Z",
        evidence_ref="evidence/20-pass",
        cleanup_confirmed=True,
    )
    assert pool.allowed_machine_ids(
        PoolEnvironment("sha256:x", "12.6", "2.9.1+cu126")
    ) == [20]


def test_enforced_client_rejects_direct_unknown_offer_id(monkeypatch, tmp_path):
    pool_path = tmp_path / "pool.json"
    pool_path.write_text('{"version": 1, "pool": []}')
    monkeypatch.setenv("VAST_VERIFIED_MACHINE_POOL_ENFORCED", "1")
    monkeypatch.setenv("VAST_VERIFIED_MACHINE_POOL_PATH", str(pool_path))
    monkeypatch.setenv("VAST_WORKER_IMAGE_DIGEST", "sha256:good")
    monkeypatch.setenv("VAST_CUDA_VERSION", "12.6")
    monkeypatch.setenv("VAST_PYTORCH_VERSION", "2.9.1+cu126")

    from src.domain.exceptions import VideoProcessingError
    from src.domain.vastai import VastInstanceConfig
    from src.infrastructure.vastai.client import VastAIClient

    client = VastAIClient(api_key="test-key")
    try:
        client.create_instance(999, VastInstanceConfig(image="x", disk=1, env={}))
    except VideoProcessingError as error:
        assert "verified machine pool" in str(error)
    else:
        raise AssertionError("unknown offer ID must be rejected before API PUT")
