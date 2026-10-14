#!/usr/bin/env python3
"""Create a deterministic, local-only archive for seeding the RIFE model volume."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

BUNDLE_MODEL_PATH = "train_log/flownet.pkl"
_MAX_MANIFEST_SOURCE_BYTES = 64 * 1024
_MAX_MODEL_SOURCE_BYTES = 128 * 1024 * 1024


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_source_without_symlinks(
    path: Path | str, *, label: str, max_bytes: int
) -> bytes:
    """Open a regular file by walking every path component with O_NOFOLLOW."""
    requested = Path(path).expanduser()
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    if ".." in requested.parts:
        raise ValueError(f"unsafe {label} source path")
    parts = requested.parts[1:]
    if not parts:
        raise ValueError(f"unsafe {label} source path")

    directory_fd = os.open(
        os.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    file_fd = -1
    try:
        for component in parts[:-1]:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
        )
        source_info = os.fstat(file_fd)
        if not stat.S_ISREG(source_info.st_mode):
            raise ValueError(f"unsafe {label} source: not a regular file")
        if source_info.st_size > max_bytes:
            raise ValueError(f"{label} source exceeds the {max_bytes}-byte limit")
        content = bytearray()
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > max_bytes:
                raise ValueError(f"{label} source exceeds the {max_bytes}-byte limit")
        if os.fstat(file_fd).st_size != len(content):
            raise ValueError(f"{label} source changed while being read")
        return bytes(content)
    except OSError as exc:
        raise ValueError(
            f"unsafe {label} source path (symlinks are forbidden)"
        ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)


def _validate_source(weights_path: Path, manifest_path: Path) -> tuple[bytes, bytes]:
    manifest_bytes = _read_source_without_symlinks(
        manifest_path, label="manifest", max_bytes=_MAX_MANIFEST_SOURCE_BYTES
    )
    try:
        manifest: Any = json.loads(manifest_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("model manifest is invalid JSON") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
    ):
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
    if (
        type(entry.get("size_bytes")) is not int
        or entry["size_bytes"] < 0
        or not isinstance(entry.get("sha256"), str)
    ):
        raise ValueError("model manifest size or sha256 is invalid")

    weights = _read_source_without_symlinks(
        weights_path, label="weights", max_bytes=_MAX_MODEL_SOURCE_BYTES
    )
    if len(weights) != entry["size_bytes"]:
        raise ValueError("model size mismatch with manifest")
    if _sha256(weights) != entry["sha256"]:
        raise ValueError("model sha256 mismatch with manifest")
    return manifest_bytes, weights


def export_bundle(
    weights_path: Path | str, manifest_path: Path | str, output_path: Path | str
) -> str:
    """Validate source artifacts, atomically write deterministic tar.gz, and return its SHA-256."""
    weights = Path(weights_path).expanduser()
    manifest = Path(manifest_path).expanduser()
    if not weights.is_absolute():
        weights = Path.cwd() / weights
    if not manifest.is_absolute():
        manifest = Path.cwd() / manifest
    output = Path(output_path).expanduser().resolve()
    if output in {Path(os.path.abspath(weights)), Path(os.path.abspath(manifest))}:
        raise ValueError("output path must not overwrite an input")
    manifest_bytes, weight_bytes = _validate_source(weights, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    os.close(fd)
    try:
        with Path(temporary_name).open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive:
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
    parser.add_argument(
        "output", type=Path, help="output path for the local tar.gz model bundle"
    )
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
    print(
        json.dumps(
            {"decision": "ALLOW", "output": str(args.output), "sha256": digest},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
