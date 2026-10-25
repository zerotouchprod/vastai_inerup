"""CPU-only tests for the RunPod Serverless worker: self-check parsing, encoder selection, handler contract."""

import json
import subprocess
import types
from pathlib import Path

import pytest

from src.serverless import encoder as enc
from src.serverless import handler as h
from src.serverless import selfcheck as sc


# ---------- self-check ----------

def test_sm_arch():
    assert sc.sm_arch((12, 0)) == "sm_120"
    assert sc.sm_arch((8, 9)) == "sm_89"
    assert sc.sm_arch(None) is None


@pytest.mark.parametrize("smi,name,want", [
    ("GPU 0: NVIDIA RTX PRO 6000 Blackwell (UUID: GPU-x)\n  MIG 1g.24gb     Device  0: (UUID: MIG-y)", "", "1g.24gb"),
    ("", "NVIDIA RTX PRO 6000 Blackwell MIG 2g.48gb", "2g.48gb"),
    ("GPU 0: NVIDIA L4 (UUID: GPU-z)", "NVIDIA L4", None),
])
def test_parse_mig(smi, name, want):
    assert sc.parse_mig_profile(smi, name) == want


def test_arch_supported():
    assert sc.arch_supported("sm_120", ["sm_90", "sm_120"])
    assert not sc.arch_supported("sm_120", ["sm_80", "sm_86", "sm_90"])  # cu126 on Blackwell
    assert sc.arch_supported("sm_121", ["compute_120"])  # PTX is JIT-able on newer archs
    # cu128 wheel list (measured): no sm_89 cubin, but sm_86 is binary-compatible with L4 (sm_89)
    cu128 = ["sm_70", "sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
    assert sc.arch_supported("sm_89", cu128) and sc.arch_supported("sm_120", cu128)
    assert not sc.arch_supported("sm_89", ["sm_90", "sm_120"])  # cubins never run on an older minor/major
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
                raise RuntimeError("CUDA error: no kernel image is available for execution on the device")
            return self

        def sum(self):
            return self

        def item(self):
            return 0.0

    cudam = types.SimpleNamespace(
        is_available=lambda: cuda, get_arch_list=lambda: list(arch), get_device_properties=lambda i: _Props(),
        get_device_capability=lambda i: cap, mem_get_info=lambda i: (20 * 10**9, 24 * 10**9), synchronize=lambda: None)
    return types.SimpleNamespace(__version__="2.9.1+cu128", version=types.SimpleNamespace(cuda="12.8"), cuda=cudam,
                                 randn=lambda *a, **k: T())


def _smi(*a, **k):
    return subprocess.CompletedProcess(a, 0, stdout="GPU 0: X\n  MIG 1g.24gb  Device 0: (UUID: MIG-1)\n", stderr="")


def test_collect_ok_blackwell_mig():
    r = sc.collect(torch_mod=_fake_torch(), run=_smi)
    assert r["ok"] and r["arch"] == "sm_120" and r["mig_profile"] == "1g.24gb"
    assert r["vram_total_gb"] == 24.0 and r["torch_cuda"] == "12.8" and r["kernel_smoke"] == "ok"
    assert "selfcheck" in sc.summary_line(r) and "sm_120" in sc.summary_line(r)


def test_collect_cu126_on_blackwell_fails():
    r = sc.collect(torch_mod=_fake_torch(arch=("sm_80", "sm_90")), run=_smi)
    assert not r["ok"] and r["reason"] == "arch_unsupported:sm_120"


def test_collect_kernel_smoke_fails():
    r = sc.collect(torch_mod=_fake_torch(smoke_ok=False), run=_smi)
    assert not r["ok"] and r["reason"] == "kernel_smoke_failed" and "no kernel image" in r["kernel_smoke"]


def test_collect_no_cuda():
    r = sc.collect(torch_mod=_fake_torch(cuda=False), run=_smi)
    assert not r["ok"] and r["reason"] == "cuda_unavailable"


# ---------- encoder ----------

def test_probe_nvenc_ok_and_fail():
    ok = enc.probe_nvenc(run=lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert ok["nvenc_ok"] and ok["nvenc_error"] is None
    bad = enc.probe_nvenc(run=lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "OpenEncodeSessionEx failed: unsupported device"))
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
    assert "-encoders" not in seen["cmd"] and "h264_nvenc" in seen["cmd"] and "null" in seen["cmd"]


@pytest.mark.parametrize("probe,override,want", [
    ({"nvenc_ok": True}, "", ("h264_nvenc", "probe_ok")),
    ({"nvenc_ok": False}, "", ("libx264", "nvenc_probe_failed")),
    ({"nvenc_ok": True}, "libx264", ("libx264", "override")),
    ({"nvenc_ok": False}, "h264_nvenc", ("libx264", "nvenc_probe_failed")),  # never force a broken nvenc
])
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

@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setitem(h._STATE, "selfcheck", {"ok": True, "gpu": "fake", "arch": "sm_89", "torch_cuda": "12.8"})
    monkeypatch.setitem(h._STATE, "encoder", {"encoder": "libx264", "reason": "nvenc_probe_failed"})
    monkeypatch.setitem(h._STATE, "probe", {"nvenc_ok": False})
    monkeypatch.setitem(h._STATE, "seen", {})
    monkeypatch.setattr(enc, "apply_to_assembler", lambda e: None)

    def fake_pipeline(task, src, dst, lost):
        h.log.info("Assembling video with encoder: libx264")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "fps=60", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(dst)], check=True)
    monkeypatch.setattr(h, "run_pipeline", fake_pipeline)
    import logging
    logging.getLogger().setLevel(logging.INFO)


def test_validate_rejects_bad_input():
    for bad in ({"input_url": "file:///etc/passwd"}, {"duration": 0}, {"duration": 999}, {"mode": "x"},
                {"params": []}, {"output_put_url": "http://plain"}, {"start": "a"}):
        with pytest.raises(h.InputError):
            h.validate(bad)
    assert h.validate({})["input_url"] == "lavfi"


def test_handler_success_contract(ready):
    out = h.handler({"id": "job-1", "input": {"input_url": "lavfi", "duration": 1, "chunk_id": "c1"}})
    assert out["ok"] is True and "error" not in out
    assert out["schema"] == 1 and out["job_id"] == "job-1" and out["chunk_id"] == "c1"
    assert len(out["output_sha256"]) == 64 and out["output_bytes"] > 0
    assert out["output_frames"] == 60 and abs(out["output_duration_s"] - 1.0) < 0.1
    assert out["encoder"] == "libx264" and out["encoder_used"] == "libx264"
    assert out["repeat_delivery"] is False
    assert {"input_s", "pipeline_s", "handler_total_s"} <= set(out["timings"])
    json.dumps(out)


def test_handler_deterministic_sha(ready):
    a = h.handler({"id": "a", "input": {"duration": 1}})
    b = h.handler({"id": "b", "input": {"duration": 1}})
    assert a["output_sha256"] == b["output_sha256"]


def test_handler_repeat_delivery_flag(ready):
    h.handler({"id": "dup", "input": {"duration": 1}})
    assert h.handler({"id": "dup", "input": {"duration": 1}})["repeat_delivery"] is True


def test_handler_failure_has_traceback_and_telemetry(ready, monkeypatch):
    def broken(task, src, dst, lost):
        h.log.info("loading RIFE")
        raise RuntimeError("CUDA error: no kernel image is available for execution on the device")
    monkeypatch.setattr(h, "run_pipeline", broken)
    puts = []
    monkeypatch.setattr(h, "_put", lambda url, path=None, body=None, ctype="": puts.append((url, body, ctype)) or 200)
    out = h.handler({"id": "j", "input": {"duration": 1, "telemetry_put_url": "https://r2.example/t.json?X-Amz-Signature=s"}})
    assert out["ok"] is False and out["error"].startswith("gpu_error")
    assert out["failure_code"] == "gpu_error" and out["failed_stage"] == "pipeline"
    assert "Traceback" in out["traceback"] and "loading RIFE" in out["log_tail"]
    assert out["refresh_worker"] is True and out["selfcheck"]["arch"] == "sm_89"
    assert out["telemetry_upload_status"] == 200
    url, body, ctype = puts[0]
    rec = json.loads(body)
    assert ctype == "application/json" and rec["failure_code"] == "gpu_error" and "traceback" in rec
    assert "X-Amz-Signature" not in json.dumps(out)  # presigned URLs never echoed


def test_handler_selfcheck_failed_refuses_cpu(ready, monkeypatch):
    monkeypatch.setitem(h._STATE, "selfcheck", {"ok": False, "reason": "arch_unsupported:sm_120"})
    called = []
    monkeypatch.setattr(h, "run_pipeline", lambda *a: called.append(1))
    out = h.handler({"id": "j", "input": {"duration": 1}})
    assert not out["ok"] and not called and "arch_unsupported" in out["error"] and out["refresh_worker"]


def test_handler_input_error(ready):
    out = h.handler({"id": "j", "input": {"mode": "nope"}})
    assert out["failure_code"] == "input_invalid" and out["failed_stage"] == "validate" and "refresh_worker" not in out


def test_handler_upload_failure(ready, monkeypatch):
    monkeypatch.setattr(h, "_put", lambda *a, **k: 403)
    out = h.handler({"id": "j", "input": {"duration": 1, "output_put_url": "https://r2.example/o.mp4"}})
    assert not out["ok"] and out["failed_stage"] == "upload" and "403" in out["error"]


def test_diag_returns_selfcheck(ready):
    out = h.handler({"id": "d", "input": {"diag": True}})
    assert out["ok"] and out["diag"]["arch"] == "sm_89" and out["nvenc"] == {"nvenc_ok": False}
