#!/usr/bin/env python3
"""Create a deterministic, local-only archive for seeding the RIFE model volume."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

BUNDLE_MODEL_PATH = "train_log/flownet.pkl"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_source(weights_path: Path, manifest_path: Path) -> tuple[bytes, bytes]:
    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest: Any = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("model manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported model manifest schema")
    if manifest.get("pipeline_version") != "aividup-rife-interp-v1":
        raise ValueError("unexpected model pipeline version")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ValueError("RIFE pilot manifest must contain exactly one model file")
    entry = files[0]
    relative_path = entry.get("path")
    if relative_path != BUNDLE_MODEL_PATH or PurePosixPath(relative_path).is_absolute():
        raise ValueError("unsafe or unsupported model path in manifest")
    if ".." in PurePosixPath(relative_path).parts or "\\" in relative_path:
        raise ValueError("unsafe model path in manifest")
    if type(entry.get("size_bytes")) is not int or entry["size_bytes"] < 0 or not isinstance(entry.get("sha256"), str):
        raise ValueError("model manifest size or sha256 is invalid")

    weights = weights_path.read_bytes()
    if len(weights) != entry["size_bytes"]:
        raise ValueError("model size mismatch with manifest")
    if _sha256(weights) != entry["sha256"]:
        raise ValueError("model sha256 mismatch with manifest")
    return manifest_bytes, weights


def export_bundle(weights_path: Path | str, manifest_path: Path | str, output_path: Path | str) -> str:
    """Validate source artifacts, atomically write deterministic tar.gz, and return its SHA-256."""
    weights = Path(weights_path).resolve(strict=True)
    manifest = Path(manifest_path).resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    if output in {weights, manifest}:
        raise ValueError("output path must not overwrite an input")
    manifest_bytes, weight_bytes = _validate_source(weights, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    try:
        with Path(temporary_name).open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    for name, content in (
                        ("manifest.json", manifest_bytes),
                        (BUNDLE_MODEL_PATH, weight_bytes),
                    ):
                        info = tarfile.TarInfo(name)
                        info.size = len(content)
                        info.mode = 0o644
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mtime = 0
                        archive.addfile(info, io.BytesIO(content))
        os.replace(temporary_name, output)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return _sha256(output.read_bytes())


def main() -> int:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="output path for the local tar.gz model bundle")
    parser.add_argument(
        "--weights",
        type=Path,
        default=repository / "RIFEv4.26_0921/train_log/flownet.pkl",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=repository / "runpod/pilot/rife-v4.26/manifest.json",
    )
    args = parser.parse_args()
    try:
        digest = export_bundle(args.weights, args.manifest, args.output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"decision": "ALLOW", "output": str(args.output), "sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
