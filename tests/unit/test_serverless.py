"""CPU-only tests for the RunPod Serverless worker: self-check parsing, encoder selection, handler contract."""

import json
import subprocess
import types

import pytest

from src.serverless import encoder as enc
from src.serverless import handler as h
from src.serverless import selfcheck as sc

# ---------- self-check ----------


def test_sm_arch():
    assert sc.sm_arch((12, 0)) == "sm_120"
    assert sc.sm_arch((8, 9)) == "sm_89"
    assert sc.sm_arch(None) is None


@pytest.mark.parametrize(
    "smi,name,want",
    [
        (
            "GPU 0: NVIDIA RTX PRO 6000 Blackwell (UUID: GPU-x)\n  MIG 1g.24gb     Device  0: (UUID: MIG-y)",
            "",
            "1g.24gb",
        ),
        ("", "NVIDIA RTX PRO 6000 Blackwell MIG 2g.48gb", "2g.48gb"),
        ("GPU 0: NVIDIA L4 (UUID: GPU-z)", "NVIDIA L4", None),
    ],
)
def test_parse_mig(smi, name, want):
    assert sc.parse_mig_profile(smi, name) == want


def test_arch_supported():
    assert sc.arch_supported("sm_120", ["sm_90", "sm_120"])
    assert not sc.arch_supported(
        "sm_120", ["sm_80", "sm_86", "sm_90"]
    )  # cu126 on Blackwell
    assert sc.arch_supported(
        "sm_121", ["compute_120"]
    )  # PTX is JIT-able on newer archs
    # cu128 wheel list (measured): no sm_89 cubin, but sm_86 is binary-compatible with L4 (sm_89)
    cu128 = ["sm_70", "sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
    assert sc.arch_supported("sm_89", cu128) and sc.arch_supported("sm_120", cu128)
    assert not sc.arch_supported(
        "sm_89", ["sm_90", "sm_120"]
    )  # cubins never run on an older minor/major
    assert not sc.arch_supported(None, ["sm_90"])


class _Props:
    name = "NVIDIA RTX PRO 6000 Blackwell MIG 1g.24gb"
    total_memory = 24 * 10**9
    multi_processor_count = 24


def _fake_torch(cap=(12, 0), arch=("sm_90", "sm_120"), cuda=True, smoke_ok=True):
    class T:
        def half(self):
            return self

        def __matmul__(self, o):
            if not smoke_ok:
                raise RuntimeError(
                    "CUDA error: no kernel image is available for execution on the device"
                )
            return self

        def sum(self):
            return self

        def item(self):
            return 0.0

    cudam = types.SimpleNamespace(
        is_available=lambda: cuda,
        get_arch_list=lambda: list(arch),
        get_device_properties=lambda i: _Props(),
        get_device_capability=lambda i: cap,
        mem_get_info=lambda i: (20 * 10**9, 24 * 10**9),
        synchronize=lambda: None,
    )
    return types.SimpleNamespace(
        __version__="2.9.1+cu128",
        version=types.SimpleNamespace(cuda="12.8"),
        cuda=cudam,
        randn=lambda *a, **k: T(),
    )


def _smi(*a, **k):
    return subprocess.CompletedProcess(
        a, 0, stdout="GPU 0: X\n  MIG 1g.24gb  Device 0: (UUID: MIG-1)\n", stderr=""
    )


def test_collect_ok_blackwell_mig():
    r = sc.collect(torch_mod=_fake_torch(), run=_smi)
    assert r["ok"] and r["arch"] == "sm_120" and r["mig_profile"] == "1g.24gb"
    assert (
        r["vram_total_gb"] == 24.0
        and r["torch_cuda"] == "12.8"
        and r["kernel_smoke"] == "ok"
    )
    assert "selfcheck" in sc.summary_line(r) and "sm_120" in sc.summary_line(r)


def test_collect_cu126_on_blackwell_fails():
    r = sc.collect(torch_mod=_fake_torch(arch=("sm_80", "sm_90")), run=_smi)
    assert not r["ok"] and r["reason"] == "arch_unsupported:sm_120"


def test_collect_kernel_smoke_fails():
    r = sc.collect(torch_mod=_fake_torch(smoke_ok=False), run=_smi)
    assert (
        not r["ok"]
        and r["reason"] == "kernel_smoke_failed"
        and "no kernel image" in r["kernel_smoke"]
    )


def test_collect_no_cuda():
    r = sc.collect(torch_mod=_fake_torch(cuda=False), run=_smi)
    assert not r["ok"] and r["reason"] == "cuda_unavailable"


# ---------- encoder ----------


def test_probe_nvenc_ok_and_fail():
    ok = enc.probe_nvenc(run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert ok["nvenc_ok"] and ok["nvenc_error"] is None
    bad = enc.probe_nvenc(
        run=lambda *a, **k: subprocess.CompletedProcess(
            a, 1, "", "OpenEncodeSessionEx failed: unsupported device"
        )
    )
    assert not bad["nvenc_ok"] and "unsupported device" in bad["nvenc_error"]

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ffmpeg", 30)

    assert not enc.probe_nvenc(run=boom)["nvenc_ok"]


def test_probe_uses_real_encode_not_listing():
    seen = {}

    def run(cmd, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    enc.probe_nvenc(run=run)
    assert (
        "-encoders" not in seen["cmd"]
        and "h264_nvenc" in seen["cmd"]
        and "null" in seen["cmd"]
    )


@pytest.mark.parametrize(
    "probe,override,want",
    [
        ({"nvenc_ok": True}, "", ("h264_nvenc", "probe_ok")),
        ({"nvenc_ok": False}, "", ("libx264", "nvenc_probe_failed")),
        ({"nvenc_ok": True}, "libx264", ("libx264", "override")),
        (
            {"nvenc_ok": False},
            "h264_nvenc",
            ("libx264", "nvenc_probe_failed"),
        ),  # never force a broken nvenc
    ],
)
def test_select_encoder(probe, override, want):
    c = enc.select_encoder(probe, override=override)
    assert (c["encoder"], c["reason"]) == want


def test_apply_to_assembler_process_local():
    from src.infrastructure.media.assembler import FFmpegAssembler

    try:
        enc.apply_to_assembler("libx264")
        assert FFmpegAssembler()._preferred_encoder == "libx264"
        enc.apply_to_assembler("h264_nvenc")  # idempotent re-wrap, no recursion
        assert FFmpegAssembler()._preferred_encoder == "h264_nvenc"
        with pytest.raises(ValueError):
            enc.apply_to_assembler("mpeg4")
    finally:
        FFmpegAssembler.__init__ = FFmpegAssembler._aividup_orig_init


# ---------- handler contract ----------

import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

FAKE = [
    sys.executable,
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "sls_fake_child.py"),
]
OUT = "https://r2.example/sls/att-12345678/o.mp4?X-Amz-Signature=s"


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setitem(
        h._STATE,
        "selfcheck",
        {"ok": True, "gpu": "fake", "arch": "sm_89", "torch_cuda": "12.8"},
    )
    monkeypatch.setitem(
        h._STATE, "encoder", {"encoder": "libx264", "reason": "nvenc_probe_failed"}
    )
    monkeypatch.setitem(h._STATE, "probe", {"nvenc_ok": False})
    monkeypatch.setitem(h._STATE, "calls", 0)
    monkeypatch.setitem(h._STATE, "seen", {})
    monkeypatch.setattr(h, "CHILD_CMD", FAKE)
    monkeypatch.setattr(h, "POLL_S", 0.1)
    monkeypatch.setattr(h, "CANCEL_POLL_S", 0.1)
    monkeypatch.setattr(h, "_runpod_cancelled", lambda jid: False)
    monkeypatch.setenv("FAKE_CHILD", "ok")


@pytest.fixture
def puts(monkeypatch):
    calls = []
    monkeypatch.setattr(
        h,
        "_put",
        lambda url, path=None, body=None, ctype="": calls.append((url, body, ctype))
        or 200,
    )
    return calls


def test_validate_rejects_bad_input():
    for bad in (
        {"input_url": "file:///etc/passwd"},
        {"duration": 0},
        {"duration": 999},
        {"mode": "x"},
        {"params": []},
        {"output_put_url": "http://plain"},
        {"start": "a"},
        {"deadline_s": 0},
        {"deadline_s": "x"},
        {"output_put_url": OUT},  # no attempt_id
        {
            "output_put_url": "https://r2.example/sls/other/o.mp4",
            "attempt_id": "att-12345678",
        },
        {
            "output_put_url": "https://r2.example/o.mp4?a=att-12345678",
            "attempt_id": "att-12345678",
        },
    ):
        with pytest.raises(h.InputError):
            h.validate(bad)
    v = h.validate({})
    assert v["input_url"] == "lavfi" and v["deadline_s"] == h.DEFAULT_DEADLINE_S
    assert (
        h.validate({"output_put_url": OUT, "attempt_id": "att-12345678"})["attempt_id"]
        == "att-12345678"
    )


def test_handler_success_contract(ready, puts):
    out = h.handler(
        {
            "id": "job-1",
            "input": {
                "duration": 1,
                "chunk_id": "c1",
                "attempt_id": "att-12345678",
                "output_put_url": OUT,
            },
        }
    )
    assert out["ok"] is True and "error" not in out, out
    assert out["schema"] == 1 and out["job_id"] == "job-1" and out["chunk_id"] == "c1"
    assert (
        len(out["output_sha256"]) == 64
        and out["output_bytes"] > 0
        and out["upload_status"] == 200
    )
    assert out["output_frames"] == 60 and abs(out["output_duration_s"] - 1.0) < 0.1
    assert out["encoder_used"] == "libx264" and out["repeat_delivery"] is False
    assert len(out["input_sha256"]) == 64 and out["input_duration_s"] == 1.0
    assert out["warm_start"] is False and out["selfcheck_s"] >= 0
    assert {"pipeline_s", "handler_total_s", "upload_s"} <= set(out["timings"])
    assert "X-Amz-Signature" not in json.dumps(out)


def test_handler_deterministic_sha(ready):
    assert (
        h.handler({"id": "a", "input": {}})["output_sha256"]
        == h.handler({"id": "b", "input": {}})["output_sha256"]
    )


def test_handler_repeat_delivery_flag(ready):
    h.handler({"id": "dup", "input": {}})
    assert h.handler({"id": "dup", "input": {}})["repeat_delivery"] is True


def test_child_cuda_failure_has_context_and_telemetry(ready, puts, monkeypatch):
    monkeypatch.setenv("FAKE_CHILD", "cuda")
    out = h.handler(
        {
            "id": "j",
            "input": {
                "telemetry_put_url": "https://r2.example/t.json?X-Amz-Signature=s"
            },
        }
    )
    assert (
        out["ok"] is False
        and out["failure_code"] == "gpu_error"
        and out["failed_stage"] == "pipeline"
    )
    assert (
        "Traceback" in out["traceback"]
        and "no kernel image" in out["log_tail"]
        and out["refresh_worker"]
    )
    assert out["telemetry_upload_status"] == 200
    rec = json.loads(puts[0][1])
    assert puts[0][2] == "application/json" and rec["failure_code"] == "gpu_error"
    assert "X-Amz-Signature" not in json.dumps(out)


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # zombie = dead
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False


def _grandchild_pid(tmp_seen):
    for _ in range(50):
        for p in tmp_seen:
            if os.path.exists(p):
                return int(open(p).read())
        time.sleep(0.1)


def test_deadline_kills_child_group_and_never_uploads(
    ready, puts, monkeypatch, tmp_path
):
    monkeypatch.setenv("FAKE_CHILD", "sleep")
    monkeypatch.setattr(h.tempfile, "TemporaryDirectory", lambda: _Keep(tmp_path))
    t = time.time()
    out = h.handler(
        {
            "id": "j",
            "input": {
                "deadline_s": 1.5,
                "attempt_id": "att-12345678",
                "output_put_url": OUT,
            },
        }
    )
    assert time.time() - t < 20
    assert (
        out["failure_code"] == "deadline_exceeded"
        and out["failed_stage"] == "pipeline"
        and "child killed" in out["error"]
    )
    assert not [p for p in puts if p[2] == "video/mp4"]  # no output upload
    gpid = int((tmp_path / "out.pid").read_text())
    assert not _pid_alive(gpid)  # grandchild (ffmpeg stand-in) killed with the group


def test_cancel_url_kills_child_no_upload_no_telemetry(
    ready, puts, monkeypatch, tmp_path
):
    monkeypatch.setenv("FAKE_CHILD", "sleep")
    monkeypatch.setattr(h.tempfile, "TemporaryDirectory", lambda: _Keep(tmp_path))
    t0 = time.time()
    monkeypatch.setattr(h, "_cancel_marker", lambda url: time.time() - t0 > 1.0)
    out = h.handler(
        {
            "id": "j",
            "input": {
                "cancel_url": "https://r2.example/cancel",
                "attempt_id": "att-12345678",
                "output_put_url": OUT,
                "telemetry_put_url": "https://r2.example/t.json",
            },
        }
    )
    assert out["failure_code"] == "cancelled" and "cancel_url" in out["error"]
    assert puts == []  # neither output nor telemetry after cancel
    assert not _pid_alive(int((tmp_path / "out.pid").read_text()))


def test_runpod_status_cancel(ready, puts, monkeypatch):
    monkeypatch.setenv("FAKE_CHILD", "sleep")
    monkeypatch.setattr(h, "_runpod_cancelled", lambda jid: True)
    out = h.handler({"id": "j", "input": {}})
    assert out["failure_code"] == "cancelled" and "runpod_status" in out["error"]


def test_cancel_after_pipeline_blocks_upload(ready, puts, monkeypatch):
    seq = iter([False] * 1000)
    monkeypatch.setattr(h, "_cancel_marker", lambda url: next(seq, True))
    real = h.run_child

    def child_then_cancel(*a, **k):
        r = real(*a, **k)
        monkeypatch.setattr(h, "_cancel_marker", lambda url: True)
        return r

    monkeypatch.setattr(h, "run_child", child_then_cancel)
    out = h.handler(
        {
            "id": "j",
            "input": {
                "cancel_url": "https://r2.example/c",
                "attempt_id": "att-12345678",
                "output_put_url": OUT,
            },
        }
    )
    assert (
        out["failure_code"] == "cancelled"
        and out["failed_stage"] == "verify"
        and puts == []
    )


def test_handler_selfcheck_failed_refuses_cpu(ready, monkeypatch):
    monkeypatch.setitem(
        h._STATE, "selfcheck", {"ok": False, "reason": "arch_unsupported:sm_120"}
    )
    out = h.handler({"id": "j", "input": {}})
    assert (
        not out["ok"] and "arch_unsupported" in out["error"] and out["refresh_worker"]
    )


def test_handler_input_error(ready):
    out = h.handler({"id": "j", "input": {"mode": "nope"}})
    assert (
        out["failure_code"] == "input_invalid"
        and out["failed_stage"] == "validate"
        and "refresh_worker" not in out
    )


def test_handler_upload_failure(ready, monkeypatch):
    monkeypatch.setattr(h, "_put", lambda *a, **k: 403)
    out = h.handler(
        {"id": "j", "input": {"attempt_id": "att-12345678", "output_put_url": OUT}}
    )
    assert not out["ok"] and out["failed_stage"] == "upload" and "403" in out["error"]


def test_diag_returns_selfcheck(ready):
    out = h.handler({"id": "d", "input": {"diag": True}})
    assert (
        out["ok"]
        and out["diag"]["arch"] == "sm_89"
        and out["nvenc"] == {"nvenc_ok": False}
    )


class _Keep:
    def __init__(self, p):
        self.p = p

    def __enter__(self):
        return str(self.p)

    def __exit__(self, *a):
        return False


# ---------- RIFE chunk-boundary frame accounting ----------

from src.serverless import boundary as bd  # noqa: E402


def _frames(p):
    return bd._probe(p)["frames"]


def _fake_rife(src, dst, factor=2):
    """Frame-count stand-in for RIFE: n source frames -> factor*(n-1)+1 frames at factor x fps."""
    info = bd._probe(src)
    n = info["frames"]
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"fps={info['fps'] * factor}",
         "-frames:v", str(factor * (n - 1) + 1), "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)],
        check=True, capture_output=True,
    )


@pytest.fixture
def source_3s(tmp_path):
    p = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=30:duration=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-shortest", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)],
        check=True, capture_output=True,
    )
    return p


def test_padded_duration_only_for_interp_modes():
    assert bd.padded_duration("both", 10.0) == 10.0 + bd.PAD_S
    assert bd.padded_duration("interp", 10.0) == 10.0 + bd.PAD_S
    assert bd.padded_duration("upscale", 10.0) == 10.0
    assert bd.PAD_S > 1 / 24


def test_chunked_interp_keeps_every_frame_across_boundaries(source_3s, tmp_path):
    """3 x 1 s chunks of a 30 fps source at 2x must give 3 x 60 = 180 frames (old behaviour: 3 x 59 = 177)."""
    from src.worker.processors import cut_chunk

    total = 0
    for i in range(3):
        cut = tmp_path / f"cut{i}.mp4"
        out = tmp_path / f"out{i}.mp4"
        cut_chunk(str(source_3s), float(i), bd.padded_duration("both", 1.0), cut, None)
        _fake_rife(cut, out)
        rep = bd.normalize_frames(out, 1.0)
        assert rep["frames_after"] == 60, rep
        total += _frames(out)
    assert total == 180


def test_unpadded_chunks_reproduce_the_old_frame_loss(source_3s, tmp_path):
    from src.worker.processors import cut_chunk

    cut, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    cut_chunk(str(source_3s), 0.0, 1.0, cut, None)
    _fake_rife(cut, out)
    assert _frames(out) == 59


def test_final_chunk_without_next_frame_is_padded_by_cloning(source_3s, tmp_path):
    from src.worker.processors import cut_chunk

    cut, out = tmp_path / "c.mp4", tmp_path / "o.mp4"
    cut_chunk(str(source_3s), 2.0, bd.padded_duration("interp", 1.0), cut, None)  # pad runs past the end
    _fake_rife(cut, out)
    rep = bd.normalize_frames(out, 1.0)
    assert rep["frames_before"] == 59 and rep["frames_after"] == 60


def test_normalize_without_audio_stream_and_noop_when_exact(tmp_path):
    p = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=60:duration=1",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p)],
        check=True, capture_output=True,
    )
    before = p.read_bytes()
    assert bd.normalize_frames(p, 1.0)["frames_after"] == 60
    assert p.read_bytes() == before  # already exact: untouched
    assert bd.normalize_frames(p, 0.5)["frames_after"] == 30
