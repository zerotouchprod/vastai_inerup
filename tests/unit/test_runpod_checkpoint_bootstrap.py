import hashlib
import http.server
import json
import os
import threading
from pathlib import Path

import pytest

from scripts.runpod_checkpoint_bootstrap import bootstrap_checkpoint


PAYLOAD = b"trusted-rife-checkpoint-payload"
MANIFEST = {
    "files": [
        {
            "path": "train_log/flownet.pkl",
            "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
            "size_bytes": len(PAYLOAD),
        }
    ],
    "model_id": "RIFE-v4.26",
    "pipeline_version": "aividup-rife-interp-v1",
    "schema_version": 1,
}


class Handler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = PAYLOAD
    declared_length = None

    def do_GET(self):
        self.send_response(self.status)
        length = len(self.body) if self.declared_length is None else self.declared_length
        self.send_header("Content-Length", str(length))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def source():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Handler.status = 200
    Handler.body = PAYLOAD
    Handler.declared_length = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/checkpoint", Handler
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def setup_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(MANIFEST))
    return path


def test_bootstrap_downloads_and_atomically_materializes_verified_checkpoint(tmp_path, source):
    url, _ = source
    root = bootstrap_checkpoint(url, setup_manifest(tmp_path), tmp_path)
    assert (root / "manifest.json").read_bytes() == json.dumps(MANIFEST).encode()
    assert (root / "train_log/flownet.pkl").read_bytes() == PAYLOAD
    assert (root / "train_log/flownet.pkl").stat().st_mode & 0o777 == 0o400
    assert root.parent.stat().st_mode & 0o777 == 0o700


def test_rejects_checkpoint_with_wrong_hash_and_leaves_no_materialized_model(tmp_path, source):
    url, handler = source
    handler.body = PAYLOAD[:-1] + b"X"
    with pytest.raises(ValueError, match="SHA-256"):
        bootstrap_checkpoint(url, setup_manifest(tmp_path), tmp_path)
    assert not list(tmp_path.glob("aividup-rife-bootstrap-*/models/rife-v4.26/train_log/flownet.pkl"))


def test_rejects_incomplete_transfer(tmp_path, source):
    url, handler = source
    Handler.body = PAYLOAD[:-4]
    Handler.declared_length = len(PAYLOAD)
    with pytest.raises(Exception):
        bootstrap_checkpoint(url, setup_manifest(tmp_path), tmp_path)


def test_rejects_http_failure(tmp_path, source):
    url, handler = source
    handler.status = 503
    with pytest.raises(Exception):
        bootstrap_checkpoint(url, setup_manifest(tmp_path), tmp_path)


def test_rejects_transfer_over_configured_maximum(tmp_path, source):
    url, _ = source
    with pytest.raises(ValueError, match="maximum"):
        bootstrap_checkpoint(url, setup_manifest(tmp_path), tmp_path, max_bytes=len(PAYLOAD) - 1)


def test_rejects_symlink_bootstrap_parent(tmp_path, source):
    url, _ = source
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    link_parent = tmp_path / "linked"
    link_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|unsafe"):
        bootstrap_checkpoint(url, setup_manifest(tmp_path), link_parent)
    assert list(real_parent.iterdir()) == []


def test_repeat_bootstrap_is_idempotent_and_uses_separate_private_roots(tmp_path, source):
    url, _ = source
    manifest = setup_manifest(tmp_path)
    first = bootstrap_checkpoint(url, manifest, tmp_path)
    second = bootstrap_checkpoint(url, manifest, tmp_path)
    assert first != second
    assert (first / "train_log/flownet.pkl").read_bytes() == PAYLOAD
    assert (second / "train_log/flownet.pkl").read_bytes() == PAYLOAD
    assert first.parent.stat().st_mode & 0o777 == second.parent.stat().st_mode & 0o777 == 0o700


def test_run_hands_verified_root_to_existing_worker_start_and_cleans_after_exit(tmp_path, source):
    from scripts.runpod_checkpoint_bootstrap import run

    url, _ = source
    manifest = setup_manifest(tmp_path)
    worker = tmp_path / "worker-start"
    capture = tmp_path / "worker-env.json"
    worker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        f"root=os.environ['AIVIDUP_MODEL_VOLUME_ROOT']; required=os.environ['AIVIDUP_MODEL_MANIFEST_REQUIRED']; assert open(root + '/train_log/flownet.pkl','rb').read() == {PAYLOAD!r}; open({str(capture)!r}, 'w').write(json.dumps({{'root':root,'required':required}}))\n"
    )
    worker.chmod(0o755)
    previous = os.environ.get("AIVIDUP_MODEL_MANIFEST_SHA256")
    os.environ["AIVIDUP_MODEL_MANIFEST_SHA256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    try:
        assert run(url, manifest, worker, tmp_path) == 0
    finally:
        if previous is None:
            os.environ.pop("AIVIDUP_MODEL_MANIFEST_SHA256", None)
        else:
            os.environ["AIVIDUP_MODEL_MANIFEST_SHA256"] = previous
    result = json.loads(capture.read_text())
    assert result["required"] == "1"
    assert not Path(result["root"]).exists()
