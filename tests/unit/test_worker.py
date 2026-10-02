import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.worker import processors as P
from src.worker.client import LeaseLost
from src.worker.runner import Worker, probe_duration

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


class FakeClient:
    def __init__(self, tasks=None, lose_after_beats=None):
        self.tasks = list(tasks or [])
        self.beats = 0
        self.completed = []
        self.failed = []
        self.lose_after_beats = lose_after_beats

    def claim(self):
        return self.tasks.pop(0) if self.tasks else None

    def heartbeat(self, attempt_id, progress=None):
        self.beats += 1
        if self.lose_after_beats is not None and self.beats > self.lose_after_beats:
            raise LeaseLost("reaped")

    def complete(self, attempt_id, output_path):
        self.completed.append((attempt_id, output_path))

    def fail(self, attempt_id, code):
        self.failed.append((attempt_id, code))


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    p = tmp_path_factory.mktemp("src") / "in.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=10",
                    "-f", "lavfi", "-i", "sine=f=440:d=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


def task(source, out, start=2.0, dur=4.0, params=None, url=None):
    return {"attempt_id": "a1", "lease_seconds": 8,
            "task": {"attempt_id": "a1", "chunk_index": 0, "input_url": url or str(source), "start_seconds": start,
                     "duration_seconds": dur, "mode": "interp", "params": params or {},
                     "output": {"type": "file", "path": str(out)}}}


def test_processes_chunk_and_reports_output(source, tmp_path):
    out = tmp_path / "res" / "c0.mp4"
    client = FakeClient([task(source, out, params={"target_fps": 60})])
    assert Worker(client, "ffmpeg", workdir=tmp_path, heartbeat_seconds=0.2).run_once() is True

    assert client.failed == [] and client.completed == [("a1", str(out))]
    assert abs(probe_duration(out) - 4.0) < 0.3
    fps = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate",
                          "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert fps == "60/1"
    assert client.beats >= 1


def test_no_task_returns_false(tmp_path):
    assert Worker(FakeClient(), "passthrough", workdir=tmp_path).run_once() is False


def test_unreadable_input_is_input_invalid(source, tmp_path):
    client = FakeClient([task(source, tmp_path / "o.mp4", url=str(tmp_path / "missing.mp4"))])
    Worker(client, "passthrough", workdir=tmp_path).run_once()
    assert client.failed == [("a1", "input_invalid")] and client.completed == []


def test_processor_failure_code_is_forwarded(source, tmp_path, monkeypatch):
    def oom(task, src, dst, lost):
        raise P.ProcessorError("out_of_memory", "CUDA out of memory")
    monkeypatch.setitem(P.PROCESSORS, "oom", oom)
    client = FakeClient([task(source, tmp_path / "o.mp4")])
    Worker(client, "oom", workdir=tmp_path).run_once()
    assert client.failed == [("a1", "out_of_memory")]


def test_unexpected_exception_is_unknown_retryable(source, tmp_path, monkeypatch):
    def boom(task, src, dst, lost):
        raise RuntimeError("segfault")
    monkeypatch.setitem(P.PROCESSORS, "boom", boom)
    client = FakeClient([task(source, tmp_path / "o.mp4")])
    Worker(client, "boom", workdir=tmp_path).run_once()
    assert client.failed == [("a1", "unknown")]


def test_wrong_duration_output_is_rejected(source, tmp_path, monkeypatch):
    def short(task, src, dst, lost):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-t", "1", "-c", "copy", str(dst)], check=True)
    monkeypatch.setitem(P.PROCESSORS, "short", short)
    out = tmp_path / "o.mp4"
    client = FakeClient([task(source, out, dur=4.0)])
    Worker(client, "short", workdir=tmp_path).run_once()
    assert client.failed == [("a1", "output_invalid")] and not out.exists()


def test_lease_lost_mid_task_drops_work_without_reporting(source, tmp_path, monkeypatch):
    def slow(task, src, dst, lost):
        for _ in range(100):
            if lost.is_set():
                raise P.ProcessorError("lease_expired", "aborted")
            time.sleep(0.05)
    monkeypatch.setitem(P.PROCESSORS, "slow", slow)
    out = tmp_path / "o.mp4"
    client = FakeClient([task(source, out)], lose_after_beats=1)
    Worker(client, "slow", workdir=tmp_path, heartbeat_seconds=0.1).run_once()
    assert client.completed == [] and client.failed == [] and not out.exists()


def test_serve_exits_when_idle(tmp_path):
    t0 = time.monotonic()
    Worker(FakeClient(), "passthrough", workdir=tmp_path).serve(poll_seconds=0.05, idle_exit_seconds=0.3)
    assert 0.3 <= time.monotonic() - t0 < 2.0


def test_workdir_is_cleaned(source, tmp_path):
    client = FakeClient([task(source, tmp_path / "res" / "o.mp4")])
    Worker(client, "passthrough", workdir=tmp_path).run_once()
    assert [p for p in tmp_path.iterdir() if p.name.startswith("chunk_")] == []


def test_put_delivery_sends_signed_headers_and_reports_url_without_query(tmp_path, monkeypatch):
    from src.worker import runner
    seen = {}

    class R:
        def raise_for_status(self):
            pass

    def fake_put(url, data, timeout, headers):
        seen.update(url=url, headers=headers, body=data.read())
        return R()

    monkeypatch.setattr(runner.requests, "put", fake_put)
    f = tmp_path / "x.mp4"
    f.write_bytes(b"abc")
    out = runner.deliver({"type": "put", "url": "https://r2.test/b/k.mp4?X-Amz-Signature=s",
                          "headers": {"x-amz-acl": "private", "Host": "r2.test"}}, f)

    assert out == "https://r2.test/b/k.mp4"
    assert seen["headers"]["x-amz-acl"] == "private" and "Host" not in seen["headers"]
    assert seen["headers"]["Content-Type"] == "video/mp4" and seen["body"] == b"abc"
