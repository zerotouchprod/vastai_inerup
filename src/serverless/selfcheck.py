"""Startup self-check for the RunPod Serverless worker: CUDA/torch versions, VRAM, GPU arch (sm_xx), MIG profile.

Everything here is safe without a GPU (returns cuda_available=False) so it is unit-testable on CPU.
"""

import os
import re
import subprocess
import traceback
from typing import Any, Callable, Dict, Optional

# "GPU 0: NVIDIA RTX PRO 6000 ... (UUID: GPU-...)" / "  MIG 1g.24gb     Device  0: (UUID: MIG-...)"
_MIG_RE = re.compile(r"MIG\s+(\d+g\.\d+gb)", re.IGNORECASE)


def sm_arch(capability) -> Optional[str]:
    """(12, 0) -> 'sm_120'."""
    if not capability:
        return None
    major, minor = int(capability[0]), int(capability[1])
    return f"sm_{major}{minor}"


def parse_mig_profile(nvidia_smi_l: str, gpu_name: str = "") -> Optional[str]:
    """MIG profile ('1g.24gb') from `nvidia-smi -L` output or the device name; None when not a MIG slice."""
    for text in (nvidia_smi_l or "", gpu_name or ""):
        m = _MIG_RE.search(text)
        if m:
            return m.group(1).lower()
    return None


def arch_supported(arch: Optional[str], arch_list) -> bool:
    """True when torch can run on this arch: an sm_XY cubin with the same major and minor <= ours
    (binary-compatible, e.g. sm_86 runs on sm_89/L4), or compute_XY PTX with XY <= ours (JIT)."""
    if not arch:
        return False
    try:
        mine = int(arch[3:])
    except ValueError:
        return False
    for a in arch_list or []:
        kind, _, num = str(a).partition("_")
        if not num.isdigit():
            continue
        n = int(num)
        if kind == "sm" and n // 10 == mine // 10 and n <= mine:
            return True
        if kind == "compute" and n <= mine:
            return True
    return False


def _nvidia_smi(run: Callable = subprocess.run) -> str:
    try:
        return run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=20).stdout[-2000:]
    except Exception as e:  # noqa: BLE001 - diagnostics only
        return f"unavailable: {type(e).__name__}"


def collect(torch_mod=None, run: Callable = subprocess.run, kernel_smoke: bool = True) -> Dict[str, Any]:
    """Self-check report. `ok` is False when CUDA is missing or the GPU arch has no kernels in this torch build."""
    out: Dict[str, Any] = {"ok": False, "revision": _revision()}
    try:
        torch = torch_mod
        if torch is None:
            import torch  # noqa: F811
        out.update(torch=torch.__version__, torch_cuda=torch.version.cuda,
                   cuda_available=bool(torch.cuda.is_available()))
        try:
            out["arch_list"] = list(torch.cuda.get_arch_list())
        except Exception:  # noqa: BLE001
            out["arch_list"] = []
        smi = _nvidia_smi(run)
        out["nvidia_smi_l"] = smi
        if not out["cuda_available"]:
            out["reason"] = "cuda_unavailable"
            return out
        props = torch.cuda.get_device_properties(0)
        cap = tuple(torch.cuda.get_device_capability(0))
        out.update(gpu=props.name, capability=list(cap), arch=sm_arch(cap),
                   vram_total_gb=round(props.total_memory / 1e9, 1), sm_count=props.multi_processor_count)
        try:
            free, total = torch.cuda.mem_get_info(0)
            out["vram_free_gb"] = round(free / 1e9, 1)
        except Exception:  # noqa: BLE001
            pass
        out["mig_profile"] = parse_mig_profile(smi, props.name)
        out["mig"] = out["mig_profile"] is not None
        if not arch_supported(out["arch"], out["arch_list"]):
            out["reason"] = f"arch_unsupported:{out['arch']}"
            return out
        if kernel_smoke:
            try:
                a = torch.randn(256, 256, device="cuda").half()
                (a @ a).sum().item()
                torch.cuda.synchronize()
                out["kernel_smoke"] = "ok"
            except Exception:  # noqa: BLE001
                out["kernel_smoke"] = traceback.format_exc()[-1500:]
                out["reason"] = "kernel_smoke_failed"
                return out
        out["ok"] = True
    except Exception:  # noqa: BLE001
        out["reason"] = "selfcheck_exception"
        out["traceback"] = traceback.format_exc()[-2000:]
    return out


def summary_line(report: Dict[str, Any]) -> str:
    keys = ("ok", "reason", "gpu", "arch", "mig_profile", "vram_total_gb", "torch", "torch_cuda", "revision")
    return "aividup-serverless selfcheck " + " ".join(f"{k}={report.get(k)}" for k in keys if k in report)


def _revision() -> str:
    try:
        with open("/etc/aividup_revision") as fh:
            return fh.read().strip()
    except OSError:
        return os.environ.get("AIVIDUP_REVISION", "unknown")
