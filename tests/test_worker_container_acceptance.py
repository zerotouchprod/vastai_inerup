from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "worker_image_container_acceptance.py"


def test_exact_image_harness_runs_container_entrypoint_not_checkout_script():
    source = SCRIPT.read_text()
    assert '"docker",\n                "run"' in source
    assert 'args.image,' in source
    assert 'scripts/worker_start.sh' not in source


def test_exact_image_harness_requires_the_published_digest_by_default():
    source = SCRIPT.read_text()
    assert "sha256:f0bf12f71b4961c54de4b8e218ca75aa28ffdd32e1371cd1fb7aa120539279ef" in source
    assert '"linux/amd64"' in source


def test_exact_image_harness_asserts_bootstrap_and_first_claim():
    source = SCRIPT.read_text()
    assert '"/api/worker/claim"' in source
    assert 'stages == ["started", "ready"]' in source
    assert 'entrypoint_matches_contract' in source
