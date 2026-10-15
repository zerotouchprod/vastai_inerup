#!/usr/bin/env python3
"""Fetch the pinned RIFE checkpoint into private ephemeral storage, then start worker."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import BinaryIO

EXPECTED_MODEL_ID = "RIFE-v4.26"
EXPECTED_PIPELINE = "aividup-rife-interp-v1"
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
CHUNK_BYTES = 64 * 1024


def _manifest_data(manifest_path: Path, expected_manifest_sha256: str) -> tuple[bytes, str, int, str]:
    data = manifest_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_manifest_sha256:
        raise ValueError("pinned model manifest SHA-256 mismatch")
    value = json.loads(data)
    if value.get("schema_version") != 1 or value.get("model_id") != EXPECTED_MODEL_ID:
        raise ValueError("unsupported or unexpected RIFE model manifest")
    if value.get("pipeline_version") != EXPECTED_PIPELINE:
        raise ValueError("unexpected RIFE pipeline version")
    files = value.get("files")
    if not isinstance(files, list) or len(files) != 1:
        raise ValueError("manifest must contain exactly one checkpoint")
    item = files[0]
    relative = item.get("path")
    if relative != "train_log/flownet.pkl":
        raise ValueError("unexpected checkpoint path in manifest")
    digest = item.get("sha256")
    size = item.get("size_bytes")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid checkpoint SHA-256 in manifest")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > DEFAULT_MAX_BYTES:
        raise ValueError("checkpoint size exceeds bootstrap maximum")
    return data, relative, size, digest


def _check_parent(parent: Path) -> Path:
    parent = parent.absolute()
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("unsafe or symlink bootstrap parent")
    # Reject symlinks in every component, including ancestors, rather than trusting resolve().
    cursor = Path(parent.anchor)
    for part in parent.parts[1:]:
        cursor = cursor / part
        info = cursor.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("unsafe or symlink bootstrap parent")
    return parent


def _open_source(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"):
        raise ValueError("checkpoint source must use HTTPS")
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": "aividup-rife-pilot"},
    )
    response = urllib.request.urlopen(request, timeout=45)
    if urllib.parse.urlparse(response.geturl()).scheme != "https" and parsed.hostname != "127.0.0.1":
        response.close()
        raise ValueError("checkpoint download redirected away from HTTPS")
    return response


def bootstrap_checkpoint(
    url: str,
    manifest_path: Path,
    parent_dir: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    expected_manifest_sha256: str | None = None,
) -> Path:
    """Return private model root after bounded, hash-checked atomic checkpoint install."""
    manifest_path = Path(manifest_path)
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = expected_manifest_sha256 or hashlib.sha256(manifest_bytes).hexdigest()
    manifest_bytes, relative, expected_size, expected_sha = _manifest_data(manifest_path, manifest_sha)
    if max_bytes <= 0 or expected_size > max_bytes:
        raise ValueError("checkpoint exceeds configured maximum")

    parent = _check_parent(Path(parent_dir))
    scratch = Path(tempfile.mkdtemp(prefix="aividup-rife-bootstrap-", dir=parent))
    scratch.chmod(0o700)
    models_dir = scratch / "models"
    models_dir.mkdir(mode=0o700)
    model_root = models_dir / "rife-v4.26"
    model_root.mkdir(mode=0o700)
    model_dir = model_root / "train_log"
    model_dir.mkdir(mode=0o700)
    try:
        manifest_tmp = model_root / ".manifest.json.part"
        with manifest_tmp.open("xb") as output:
            output.write(manifest_bytes)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(manifest_tmp, 0o400)
        os.replace(manifest_tmp, model_root / "manifest.json")

        destination = model_root.joinpath(*PurePosixPath(relative).parts)
        if destination.is_symlink():
            raise ValueError("unsafe symlink checkpoint destination")
        temp_fd, temp_name = tempfile.mkstemp(prefix=".flownet.", suffix=".part", dir=model_dir)
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        count = 0
        try:
            with os.fdopen(temp_fd, "wb") as output, _open_source(url) as response:
                length_header = response.headers.get("Content-Length")
                if length_header is not None:
                    try:
                        declared = int(length_header)
                    except ValueError as exc:
                        raise ValueError("invalid checkpoint Content-Length") from exc
                    if declared > max_bytes:
                        raise ValueError("checkpoint exceeds configured maximum")
                    if declared != expected_size:
                        raise ValueError("checkpoint transfer size does not match manifest")
                while True:
                    chunk = response.read(min(CHUNK_BYTES, max_bytes - count + 1))
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > max_bytes:
                        raise ValueError("checkpoint exceeds configured maximum")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if count != expected_size:
                raise ValueError("checkpoint transfer size does not match manifest")
            if digest.hexdigest() != expected_sha:
                raise ValueError("checkpoint SHA-256 does not match manifest")
            os.chmod(temp_path, 0o400)
            os.replace(temp_path, destination)
            directory_fd = os.open(model_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        return model_root
    except BaseException:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def run(url: str, manifest_path: Path, worker_start: Path, parent_dir: Path) -> int:
    model_root = bootstrap_checkpoint(
        url,
        manifest_path,
        parent_dir,
        expected_manifest_sha256=os.environ["AIVIDUP_MODEL_MANIFEST_SHA256"],
    )
    environment = os.environ.copy()
    environment["AIVIDUP_MODEL_VOLUME_ROOT"] = str(model_root)
    environment["AIVIDUP_MODEL_MANIFEST_REQUIRED"] = "1"
    try:
        return subprocess.call([str(worker_start)], env=environment)
    finally:
        shutil.rmtree(model_root.parents[1], ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-url", default=os.environ.get("AIVIDUP_RIFE_CHECKPOINT_URL", ""))
    parser.add_argument("--manifest", type=Path, default=Path("/opt/aividup/model-manifest.expected.json"))
    parser.add_argument("--worker-start", type=Path, default=Path("/opt/aividup/worker_start.sh"))
    parser.add_argument("--temp-parent", type=Path, default=Path("/tmp"))
    args = parser.parse_args()
    if not args.source_url:
        print("ERROR: AIVIDUP_RIFE_CHECKPOINT_URL is required", file=sys.stderr)
        return 2
    try:
        return run(args.source_url, args.manifest, args.worker_start, args.temp_parent)
    except Exception as exc:
        # Never print signed redirect URLs or response contents.
        print(f"ERROR: RIFE checkpoint bootstrap refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
