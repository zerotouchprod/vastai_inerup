#!/usr/bin/env python3
"""Helper utilities for batch sizing and OOM detection used by run_realesrgan_pytorch.sh.
This module is intentionally small and pure-Python so it can be unit-tested easily.
"""
from typing import List, Tuple
import re


def compute_batch_from_min_gpu_gb(min_gpu_gb: int) -> int:
    """Map minimum per-GPU memory (in GB) to conservative batch sizes.

    Rules (empirical):
    - <12GB => 1
    - 12-15 => 2
    - 16-23 => 4
    - 24-31 => 8
    - >=32 => 16
    """
    if min_gpu_gb < 12:
        return 1
    if min_gpu_gb < 16:
        return 2
    if min_gpu_gb < 24:
        return 4
    if min_gpu_gb < 32:
        return 8
    return 16


def parse_mem_list_mb(mem_lines: List[str]) -> List[int]:
    """Parse lines containing GPU memory numbers in MiB and return list of ints (MiB).
    Accepts strings like '16276' or '16276 MiB' or '16276\n'.
    """
    out = []
    for ln in mem_lines:
        ln = ln.strip()
        if not ln:
            continue
        m = re.search(r"(\d+)", ln)
        if m:
            out.append(int(m.group(1)))
    return out


def choose_batch_from_mem_list_mb(mem_mb_list: List[int]) -> Tuple[int,int]:
    """Given list of per-GPU memory values in MiB, return (min_gpu_gb, batch_size).
    If list is empty, return (0, 1).
    """
    if not mem_mb_list:
        return 0, 1
    min_mb = min(mem_mb_list)
    gb = min_mb // 1024
    batch = compute_batch_from_min_gpu_gb(gb)
    return gb, batch


def detect_oom_in_text(text: str) -> bool:
    """Return True if text looks like an OOM/CUDA out-of-memory report.
    Heuristics: search for keywords often present in torch/cuda OOM traces.
    """
    if not text:
        return False
    keywords = [
        r"out of memory",
        r"CUDA error",
        r"cuCtx",
        r"cudnn",
        r"OOM",
        r"out_of_memory",
        r"Resource exhausted",
    ]
    low = text.lower()
    for kw in keywords:
        if re.search(kw.lower(), low):
            return True
    return False


if __name__ == '__main__':
    import sys
    # simple CLI: pass mem values as args and print chosen batch
    if len(sys.argv) > 1:
        try:
            vals = [int(x) for x in sys.argv[1:]]
        except Exception:
            print("Invalid args: expected integers (MiB)")
            sys.exit(2)
        gb, batch = choose_batch_from_mem_list_mb(vals)
        print(f"min_gpu_gb={gb} batch={batch}")
    else:
        print("Usage: batch_helper.py <mem_mb_1> <mem_mb_2> ...")
        sys.exit(1)

