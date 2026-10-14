#!/usr/bin/env python3
"""Fail-closed validation and safe materialization of versioned RIFE volume artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
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


def _open_or_create_private_scratch(
    parent_path: Path | str, prefix: str
) -> tuple[int, int, str, str]:
    """Create an exclusively owned 0700 directory under an already trusted parent.

    The parent is pinned by fd before creation. Other UIDs cannot enumerate or
    mutate the resulting scratch tree; processes running as this UID are part
    of the trusted worker boundary (see docs/RUNPOD_RIFE_PILOT.md).
    """
    parent = Path(parent_path).expanduser()
    if not parent.is_absolute():
        parent = Path.cwd() / parent
    parent_fd = _open_volume_root(parent)
    name = f"{prefix}{os.getpid()}-{os.urandom(16).hex()}"
    scratch_fd = -1
    created = False
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        created = True
        scratch_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        info = os.fstat(scratch_fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError(
                "verified-model scratch ownership or permissions are unsafe"
            )
        result = (scratch_fd, parent_fd, name, str(parent / name))
        scratch_fd = -1
        parent_fd = -1
        return result
    except Exception:
        if scratch_fd >= 0:
            try:
                _remove_tree_contents(scratch_fd)
            finally:
                os.close(scratch_fd)
        if created:
            os.rmdir(name, dir_fd=parent_fd)
        raise
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValueError("unsafe verified-model output path") from exc


def _write_verified_at(root_fd: int, parts: tuple[str, ...], content: bytes) -> str:
    directory_fd = os.dup(root_fd)
    file_fd = -1
    try:
        for component in parts[:-1]:
            next_fd = _open_child_directory(directory_fd, component, create=True)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(
            parts[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("short write while materializing verified model")
            view = view[written:]
        os.fsync(file_fd)
        os.fchmod(file_fd, 0o400)
        os.close(file_fd)
        file_fd = -1

        # Re-open the directory entry without following links and hash the
        # bytes actually present there, not just the source buffer.
        check_fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd
        )
        try:
            actual = bytearray()
            while True:
                chunk = os.read(check_fd, 1024 * 1024)
                if not chunk:
                    break
                actual.extend(chunk)
            if not stat.S_ISREG(os.fstat(check_fd).st_mode) or _sha256(
                bytes(actual)
            ) != _sha256(content):
                raise ValueError("verified model hash mismatch after materialization")
        finally:
            os.close(check_fd)
        return "/".join(parts)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)


def _remove_tree_contents(directory_fd: int) -> None:
    for name in os.listdir(directory_fd):
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            try:
                _remove_tree_contents(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(name, dir_fd=directory_fd)
        else:
            os.unlink(name, dir_fd=directory_fd)


def _materialize_file(
    output_parent: Path | str, relative_path: str, content: bytes
) -> tuple[Path, str]:
    parts = _safe_parts(relative_path)
    root_fd, parent_fd, root_name, root_path = _open_or_create_private_scratch(
        output_parent, "aividup-verified-"
    )
    try:
        relative = _write_verified_at(root_fd, parts, content)
        return Path(root_path) / relative, root_path
    except Exception:
        # Remove only through the pinned directory FD; symlinks are unlinked,
        # never traversed. A hostile concurrent change fails cleanup closed.
        _remove_tree_contents(root_fd)
        os.close(root_fd)
        root_fd = -1
        os.rmdir(root_name, dir_fd=parent_fd)
        raise
    finally:
        if root_fd >= 0:
            os.close(root_fd)
        os.close(parent_fd)


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
        if (
            not _SHA256_RE.fullmatch(expected_sha256)
            or pinned_sha256 != expected_sha256
        ):
            raise ValueError(
                "expected manifest digest does not match the image-pinned manifest"
            )

    try:
        manifest: Any = json.loads(expected_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("image-pinned model manifest is invalid JSON") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
    ):
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
            raise ValueError(
                "mounted manifest does not match the image-pinned manifest"
            )

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
            target, materialized_root = _materialize_file(
                materialize_to, relative_path, model_bytes
            )
            result["materialized_root"] = materialized_root
            result["materialized_files"] = [
                {"path": str(target), "sha256": model_sha256}
            ]
            result["verify_materialize_seconds"] = round(
                time.monotonic() - started_at, 6
            )
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
    parser.add_argument(
        "--expected-sha256", default=os.environ.get("AIVIDUP_MODEL_MANIFEST_SHA256", "")
    )
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
