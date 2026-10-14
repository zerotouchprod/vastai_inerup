import hashlib
import json
from pathlib import Path

import pytest

from scripts.validate_rife_manifest import verify_bundle

PIPELINE = "aividup-rife-interp-v1"
MODEL = b"pinned RIFE weights"


def make_expected_manifest(path: Path) -> Path:
    manifest = {
        "schema_version": 1,
        "pipeline_version": PIPELINE,
        "model_id": "RIFE-v4.26",
        "files": [
            {
                "path": "train_log/flownet.pkl",
                "size_bytes": len(MODEL),
                "sha256": hashlib.sha256(MODEL).hexdigest(),
            }
        ],
    }
    path.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def make_volume(root: Path, manifest_bytes: bytes | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    model = root / "train_log" / "flownet.pkl"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(MODEL)
    if manifest_bytes is None:
        expected = make_expected_manifest(root / "expected.json")
        manifest_bytes = expected.read_bytes()
    (root / "manifest.json").write_bytes(manifest_bytes)
    return root


def test_accepts_exact_manifest_and_model_bundle(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())

    result = verify_bundle(
        volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
    )

    assert result["pipeline_version"] == PIPELINE
    assert result["verified_files"][0]["path"] == "train_log/flownet.pkl"


def test_rejects_manifest_not_pinned_by_image(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    altered = expected.read_bytes().replace(b"RIFE-v4.26", b"RIFE-v4.27")
    volume = make_volume(tmp_path / "volume", altered)

    with pytest.raises(ValueError, match="manifest.*pinned|pinned.*manifest"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_wrong_image_manifest_digest(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())

    with pytest.raises(ValueError, match="expected manifest digest"):
        verify_bundle(volume, expected, "0" * 64)


def test_rejects_model_checksum_mismatch(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())
    (volume / "train_log" / "flownet.pkl").write_bytes(b"x" * len(MODEL))

    with pytest.raises(ValueError, match="sha256 mismatch"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_path_traversal(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    value = json.loads(expected.read_text())
    value["files"][0]["path"] = "../../outside.pkl"
    malicious = tmp_path / "malicious.json"
    malicious.write_text(json.dumps(value))
    volume = make_volume(tmp_path / "volume", malicious.read_bytes())

    with pytest.raises(ValueError, match="unsafe model path"):
        verify_bundle(
            volume, malicious, hashlib.sha256(malicious.read_bytes()).hexdigest()
        )


def test_rejects_symlink_outside_volume(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = tmp_path / "volume"
    volume.mkdir()
    outside = tmp_path / "outside.pkl"
    outside.write_bytes(MODEL)
    model = volume / "train_log" / "flownet.pkl"
    model.parent.mkdir()
    model.symlink_to(outside)
    (volume / "manifest.json").write_bytes(expected.read_bytes())

    with pytest.raises(ValueError, match="unsafe model path"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_symlinked_volume_root(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())
    alias = tmp_path / "volume-alias"
    alias.symlink_to(volume, target_is_directory=True)

    with pytest.raises(ValueError, match="model volume root is unavailable or unsafe"):
        verify_bundle(
            alias, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_symlinked_volume_manifest(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = tmp_path / "volume"
    volume.mkdir()
    outside = tmp_path / "outside-manifest.json"
    outside.write_bytes(expected.read_bytes())
    (volume / "manifest.json").symlink_to(outside)
    model = volume / "train_log" / "flownet.pkl"
    model.parent.mkdir()
    model.write_bytes(MODEL)

    with pytest.raises(ValueError, match="unsafe volume manifest path"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_symlink_swap_between_path_check_and_model_read(tmp_path, monkeypatch):
    import os

    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())
    model = volume / "train_log" / "flownet.pkl"
    outside = tmp_path / "outside.pkl"
    outside.write_bytes(MODEL)
    real_open = os.open

    def swap_before_open(path, flags, *args, **kwargs):
        if path == "flownet.pkl" and kwargs.get("dir_fd") is not None:
            model.unlink()
            model.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_before_open)
    with pytest.raises(ValueError, match="unsafe model path"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_rejects_boolean_model_size_in_manifest(tmp_path):
    value = {
        "schema_version": 1,
        "pipeline_version": PIPELINE,
        "model_id": "RIFE-v4.26",
        "files": [
            {
                "path": "train_log/flownet.pkl",
                "size_bytes": True,
                "sha256": hashlib.sha256(b"x").hexdigest(),
            }
        ],
    }
    expected = tmp_path / "expected.json"
    manifest_bytes = json.dumps(value).encode()
    expected.write_bytes(manifest_bytes)
    volume = make_volume(tmp_path / "volume", manifest_bytes)
    (volume / "train_log" / "flownet.pkl").write_bytes(b"x")

    with pytest.raises(ValueError, match="size or sha256 is invalid"):
        verify_bundle(volume, expected, hashlib.sha256(manifest_bytes).hexdigest())


def test_rejects_model_size_mismatch(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())
    (volume / "train_log" / "flownet.pkl").write_bytes(MODEL + b"extra")

    with pytest.raises(ValueError, match="size mismatch"):
        verify_bundle(
            volume, expected, hashlib.sha256(expected.read_bytes()).hexdigest()
        )


def test_materialized_verified_model_isolated_from_volume_mutation(tmp_path):
    expected = make_expected_manifest(tmp_path / "expected.json")
    volume = make_volume(tmp_path / "volume", expected.read_bytes())
    scratch = tmp_path / "scratch"

    result = verify_bundle(
        volume,
        expected,
        hashlib.sha256(expected.read_bytes()).hexdigest(),
        materialize_to=scratch,
    )

    materialized = scratch / "train_log" / "flownet.pkl"
    assert materialized.read_bytes() == MODEL
    (volume / "train_log" / "flownet.pkl").write_bytes(b"changed volume weights")
    assert materialized.read_bytes() == MODEL
    assert result["materialized_files"][0]["path"] == str(materialized)
