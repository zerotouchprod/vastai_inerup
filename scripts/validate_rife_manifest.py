#!/usr/bin/env python3
"""Fail-closed validation and safe materialization of versioned RIFE volume artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PIPELINE_VERSION = "aividup-rife-interp-v1"
_MODEL_PATH = "train_log/flownet.pkl"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_parts(relative_path: Any) -> tuple[str, ...]:
    if not isinstance(relative_path, str) or not relative_path or "\\" in relative_path:
        raise ValueError("unsafe model path in manifest")
    path = PurePosixPath(relative_path)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError("unsafe model path in manifest")
    if str(path) != relative_path:
        raise ValueError("non-canonical model path in manifest")
    return path.parts


def _open_volume_root(volume_root: Path | str) -> int:
    requested = Path(volume_root).expanduser()
    if not str(requested):
        raise ValueError("model volume root is unavailable or unsafe")
    if not requested.is_absolute():
        requested = Path.cwd() / requested
    components = requested.parts[1:]
    if any(component in ("", ".", "..") for component in components):
        raise ValueError("model volume root is unavailable or unsafe")

    directory_fd = -1
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory_fd = os.open(os.sep, flags)
        for component in components:
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except OSError as exc:
        if directory_fd >= 0:
            os.close(directory_fd)
        raise ValueError("model volume root is unavailable or unsafe") from exc


def _read_volume_file(
    root_fd: int,
    relative_path: str,
    *,
    purpose: str,
    expected_size: int | None = None,
) -> bytes:
    parts = _safe_parts(relative_path)
    directory_fd = os.dup(root_fd)
    file_fd = -1
    try:
        for component in parts[:-1]:
            try:
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
            except OSError as exc:
                raise ValueError(f"unsafe {purpose} path") from exc
            os.close(directory_fd)
            directory_fd = next_fd
        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
        except OSError as exc:
            raise ValueError(f"unsafe {purpose} path") from exc
    finally:
        os.close(directory_fd)

    try:
        initial = os.fstat(file_fd)
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError(f"unsafe {purpose} path: not a regular file")
        if expected_size is not None and initial.st_size != expected_size:
            raise ValueError("model size mismatch with manifest")
        content = bytearray()
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if expected_size is not None and len(content) > expected_size:
                raise ValueError("model size mismatch with manifest")
        if expected_size is not None and len(content) != expected_size:
            raise ValueError("model size mismatch with manifest")
        if os.fstat(file_fd).st_size != len(content):
            raise ValueError(f"{purpose} changed while being read")
        return bytes(content)
    finally:
        os.close(file_fd)


def _materialize_file(output_root: Path | str, relative_path: str, content: bytes) -> Path:
    parts = _safe_parts(relative_path)
    root = Path(output_root).expanduser()
    if root.is_symlink():
        raise ValueError("unsafe verified-model output root")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink() or not target.parent.resolve(strict=True).is_relative_to(root):
        raise ValueError("unsafe verified-model output path")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, 0o444)
        os.replace(temporary_name, target)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return target


def verify_bundle(
    volume_root: Path | str,
    expected_manifest: Path | str,
    expected_sha256: str = "",
    *,
    materialize_to: Path | str | None = None,
) -> dict[str, Any]:
    """Verify the mounted bundle and optionally copy verified bytes to private local scratch."""
    expected_path = Path(expected_manifest)
    try:
        expected_bytes = expected_path.read_bytes()
    except OSError as exc:
        raise ValueError("image-pinned model manifest is unavailable") from exc
    pinned_sha256 = _sha256(expected_bytes)
    if expected_sha256:
        if not _SHA256_RE.fullmatch(expected_sha256) or pinned_sha256 != expected_sha256:
            raise ValueError("expected manifest digest does not match the image-pinned manifest")

    try:
        manifest: Any = json.loads(expected_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("image-pinned model manifest is invalid JSON") from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("unsupported model manifest schema")
    if manifest.get("pipeline_version") != _PIPELINE_VERSION:
        raise ValueError("unexpected model pipeline version")
    if not isinstance(manifest.get("model_id"), str) or not manifest["model_id"]:
        raise ValueError("model manifest id is invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ValueError("RIFE pilot manifest must contain exactly one model file")
    entry = files[0]
    relative_path = entry.get("path")
    _safe_parts(relative_path)
    if relative_path != _MODEL_PATH:
        raise ValueError("unsupported model path in manifest")
    if type(entry.get("size_bytes")) is not int or entry["size_bytes"] < 0:
        raise ValueError("model manifest size or sha256 is invalid")
    model_sha256 = entry.get("sha256")
    if not isinstance(model_sha256, str) or not _SHA256_RE.fullmatch(model_sha256):
        raise ValueError("model manifest size or sha256 is invalid")

    root_fd = _open_volume_root(volume_root)
    started_at = time.monotonic()
    try:
        try:
            volume_manifest = _read_volume_file(
                root_fd, "manifest.json", purpose="volume manifest"
            )
        except ValueError as exc:
            raise ValueError("unsafe volume manifest path") from exc
        if volume_manifest != expected_bytes:
            raise ValueError("mounted manifest does not match the image-pinned manifest")

        model_bytes = _read_volume_file(
            root_fd,
            relative_path,
            purpose="model",
            expected_size=entry["size_bytes"],
        )
        if _sha256(model_bytes) != model_sha256:
            raise ValueError("model sha256 mismatch with manifest")

        verified_files = [
            {
                "path": relative_path,
                "size_bytes": len(model_bytes),
                "sha256": model_sha256,
            }
        ]
        result: dict[str, Any] = {
            "decision": "ALLOW",
            "manifest_sha256": pinned_sha256,
            "model_id": manifest["model_id"],
            "pipeline_version": manifest["pipeline_version"],
            "verified_files": verified_files,
        }
        if materialize_to is not None:
            target = _materialize_file(materialize_to, relative_path, model_bytes)
            result["materialized_files"] = [{"path": str(target), "sha256": model_sha256}]
            result["verify_materialize_seconds"] = round(time.monotonic() - started_at, 6)
        return result
    finally:
        os.close(root_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--volume-root", type=Path, required=True)
    parser.add_argument(
        "--expected-manifest",
        type=Path,
        default=Path("/opt/aividup/model-manifest.expected.json"),
    )
    parser.add_argument("--expected-sha256", default=os.environ.get("AIVIDUP_MODEL_MANIFEST_SHA256", ""))
    parser.add_argument("--materialize-to", type=Path)
    args = parser.parse_args()
    try:
        result = verify_bundle(
            args.volume_root,
            args.expected_manifest,
            args.expected_sha256,
            materialize_to=args.materialize_to,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
