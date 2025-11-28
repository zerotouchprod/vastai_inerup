#!/usr/bin/env python3
"""Run batch upscaling script with automatic retry-on-OOM logic.
This module is intended to be invoked from bash and from unit tests.
"""
from __future__ import annotations
import sys
import subprocess
import shutil
import os
import glob
import time
from typing import Optional, Tuple
from scripts.batch_helper import detect_oom_in_text

BATCH_SAFE = "/workspace/project/realesrgan_batch_safe.sh"


def parse_batch_from_args(batch_args: str) -> Optional[int]:
    # find --batch-size N or --batch-size=N
    import re
    m = re.search(r"--batch-size(?:=|\s+)(\d+)", batch_args)
    if m:
        return int(m.group(1))
    return None


def run_command(cmd: list, cwd: Optional[str] = None, timeout: Optional[int] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, timeout=timeout)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def last_batch_log() -> Optional[str]:
    logs = sorted(glob.glob('/tmp/realesrgan_batch_safe_*.log'), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


def any_output_in_dir(out_dir: str) -> bool:
    try:
        return any(os.path.isfile(os.path.join(out_dir, f)) for f in os.listdir(out_dir))
    except Exception:
        return False


def run_batch_with_retries(input_dir: str, output_dir: str, batch_args: str, scale_arg: str, mode: str = 'scale', max_retries: int = 5, dry_run: bool = False) -> int:
    """Run the batch_safe script with adaptive retries on OOM.
    Returns 0 on success, non-zero on failure.
    """
    # determine initial batch from batch_args if present
    current_batch = parse_batch_from_args(batch_args) or 0
    # If no explicit batch in BATCH_ARGS, we rely on existing args (they may include a suggested digit at end)
    if current_batch <= 0:
        # try to extract trailing number
        import re
        m = re.search(r"(\d+)\s*$", batch_args)
        if m:
            try:
                current_batch = int(m.group(1))
            except Exception:
                current_batch = 0
    if current_batch <= 0:
        current_batch = 1

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        print(f"[batch] Attempt #{attempt} with --batch-size {current_batch}")
        # build args: remove any --batch-size in batch_args
        import re
        args_no_batch = re.sub(r"--batch-size(?:=|\s+)\d+", "", batch_args).strip()
        call_args = f"{args_no_batch} --batch-size {current_batch}".strip()
        # assemble command
        cmd = ["bash", BATCH_SAFE, input_dir, output_dir] + call_args.split() + (["--target-height", str(scale_arg), "--device", "cuda"] if mode == 'target-height' else ["--scale", str(scale_arg), "--device", "cuda"])
        print(f"[batch] Calling: {' '.join(cmd)}")
        if dry_run:
            # simulate success if dry_run
            return 0
        rc, out, err = run_command(cmd)
        print(out)
        if (rc == 0) and any_output_in_dir(output_dir):
            print("[batch] Completed successfully")
            return 0
        # inspect recent log for OOM
        oom_detected = False
        logpath = last_batch_log()
        if logpath:
            try:
                with open(logpath, 'r', encoding='utf-8', errors='ignore') as fh:
                    txt = fh.read()
                    if detect_oom_in_text(txt):
                        oom_detected = True
            except Exception:
                pass
        # also scan stderr/out
        if not oom_detected and detect_oom_in_text(out + '\n' + err):
            oom_detected = True
        if rc != 0:
            # conservative: treat non-zero rc as possible OOM
            oom_detected = oom_detected or True
        if oom_detected:
            new_batch = max(1, current_batch // 2)
            if new_batch >= current_batch:
                print(f"[batch] Cannot reduce batch further (current={current_batch}). Aborting retries.")
                break
            print(f"[batch] Detected OOM-like failure; reducing batch from {current_batch} -> {new_batch} and retrying")
            current_batch = new_batch
            time.sleep(1)
            continue
        else:
            print("[batch] Failure not recognized as OOM; not retrying")
            break
    return 1


if __name__ == '__main__':
    # CLI invocation: input_dir, output_dir, batch_args, scale_arg, mode(optional)
    if len(sys.argv) < 5:
        print("Usage: batch_runner.py <input_dir> <output_dir> <batch_args> <scale_arg> [mode]")
        sys.exit(2)
    input_dir = sys.argv[1]
    output_dir = sys.argv[2]
    batch_args = sys.argv[3]
    scale_arg = sys.argv[4]
    mode = sys.argv[5] if len(sys.argv) > 5 else 'scale'
    rc = run_batch_with_retries(input_dir, output_dir, batch_args, scale_arg, mode)
    sys.exit(rc)

