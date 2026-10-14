import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from scripts.export_runpod_rife_bundle import export_bundle


def make_source(root: Path, payload: bytes = b"pinned RIFE weights"):
    weights = root / "repo" / "RIFEv4.26_0921" / "train_log" / "flownet.pkl"
    weights.parent.mkdir(parents=True, exist_ok=True)
    weights.write_bytes(payload)
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline_version": "aividup-rife-interp-v1",
                "model_id": "RIFE-v4.26",
                "files": [
                    {
                        "path": "train_log/flownet.pkl",
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return weights, manifest


def test_exported_bundle_has_only_manifest_and_pinned_weights_and_is_reproducible(
    tmp_path,
):
    weights, manifest = make_source(tmp_path)
    first, second = tmp_path / "first.tar.gz", tmp_path / "second.tar.gz"

    first_sha = export_bundle(weights, manifest, first)
    second_sha = export_bundle(weights, manifest, second)

    assert first_sha == second_sha
    with tarfile.open(first, "r:gz") as archive:
        assert sorted(archive.getnames()) == ["manifest.json", "train_log/flownet.pkl"]
        assert (
            archive.extractfile("train_log/flownet.pkl").read() == weights.read_bytes()
        )
        assert archive.extractfile("manifest.json").read() == manifest.read_bytes()


def test_export_refuses_to_overwrite_inputs(tmp_path):
    weights, manifest = make_source(tmp_path)
    original_weights = weights.read_bytes()
    original_manifest = manifest.read_bytes()

    with pytest.raises(ValueError, match="output path must not overwrite an input"):
        export_bundle(weights, manifest, weights)
    assert weights.read_bytes() == original_weights

    with pytest.raises(ValueError, match="output path must not overwrite an input"):
        export_bundle(weights, manifest, manifest)
    assert manifest.read_bytes() == original_manifest


def test_export_refuses_boolean_model_size(tmp_path):
    weights = tmp_path / "flownet.pkl"
    weights.write_bytes(b"x")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline_version": "aividup-rife-interp-v1",
                "model_id": "RIFE-v4.26",
                "files": [
                    {
                        "path": "train_log/flownet.pkl",
                        "size_bytes": True,
                        "sha256": hashlib.sha256(b"x").hexdigest(),
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="size or sha256 is invalid"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_refuses_boolean_schema_version(tmp_path):
    weights, manifest = make_source(tmp_path)
    value = json.loads(manifest.read_text())
    value["schema_version"] = True
    manifest.write_text(json.dumps(value))

    with pytest.raises(ValueError, match="unsupported model manifest schema"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_refuses_weights_that_do_not_match_manifest(tmp_path):
    weights, manifest = make_source(tmp_path)
    weights.write_bytes(b"untrusted model weights")
    output = tmp_path / "should-not-exist.tar.gz"

    with pytest.raises(ValueError, match="model.*(size|sha256) mismatch"):
        export_bundle(weights, manifest, output)
    assert not output.exists()


def test_export_caps_source_manifest_size(tmp_path):
    weights, manifest = make_source(tmp_path)
    manifest.write_bytes(b"x" * (64 * 1024 + 1))

    with pytest.raises(ValueError, match="manifest source exceeds"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_caps_source_model_size(tmp_path, monkeypatch):
    import scripts.export_runpod_rife_bundle as exporter

    weights, manifest = make_source(tmp_path)
    monkeypatch.setattr(
        exporter, "_MAX_MODEL_SOURCE_BYTES", len(b"pinned RIFE weights") - 1
    )

    with pytest.raises(ValueError, match="weights source exceeds"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_rejects_symlinked_final_weight_source(tmp_path):
    weights, manifest = make_source(tmp_path)
    alias = tmp_path / "weights-link.pkl"
    alias.symlink_to(weights)

    with pytest.raises(ValueError, match="symlinks are forbidden"):
        export_bundle(alias, manifest, tmp_path / "bundle.tar.gz")


def test_export_rejects_symlinked_final_manifest_source(tmp_path):
    weights, manifest = make_source(tmp_path)
    alias = tmp_path / "manifest-link.json"
    alias.symlink_to(manifest)

    with pytest.raises(ValueError, match="symlinks are forbidden"):
        export_bundle(weights, alias, tmp_path / "bundle.tar.gz")


def test_export_rejects_symlinked_parent_source_directory(tmp_path):
    weights, manifest = make_source(tmp_path)
    repo_alias = tmp_path / "repo-link"
    repo_alias.symlink_to(weights.parents[1], target_is_directory=True)
    aliased_weights = repo_alias / "train_log" / "flownet.pkl"

    with pytest.raises(ValueError, match="symlinks are forbidden"):
        export_bundle(aliased_weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_rejects_source_symlink_swap_before_open(tmp_path, monkeypatch):
    import os

    weights, manifest = make_source(tmp_path)
    outside = tmp_path / "outside.pkl"
    outside.write_bytes(weights.read_bytes())
    real_open = os.open
    swapped = False

    def swap_source_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "flownet.pkl" and kwargs.get("dir_fd") is not None and not swapped:
            weights.unlink()
            weights.symlink_to(outside)
            swapped = True
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_source_before_open)
    with pytest.raises(ValueError, match="symlinks are forbidden"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")


def test_export_failure_cleans_temporary_bundle(tmp_path, monkeypatch):
    import os

    weights, manifest = make_source(tmp_path)
    real_replace = os.replace

    def fail_replace(*_args):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected replace failure"):
        export_bundle(weights, manifest, tmp_path / "bundle.tar.gz")
    assert not list(tmp_path.glob(".bundle.tar.gz.*"))
    monkeypatch.setattr(os, "replace", real_replace)
