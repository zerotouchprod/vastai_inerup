#!/usr/bin/env python3
"""Immutable worker-derived GPU smoke runner.

The CPU-only mode is a no-rent entrypoint contract check. GPU mode runs the
real preflight and model inference, then emits exactly one machine-readable
result line.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

EXPECTED_DIGEST = (
    "sha256:50de56d6768ec37751e5c446ac4e034d5d451ffe01f3e147340c79925c113879"
)
PREFLIGHT = Path("/opt/aividup/cuda_runtime_preflight.py")


def run_preflight():
    try:
        p = subprocess.run(
            [sys.executable, str(PREFLIGHT)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return {
            "exit_code": p.returncode,
            "stdout_tail": p.stdout[-1000:],
            "stderr_tail": p.stderr[-1000:],
        }
    except Exception as exc:
        return {"exit_code": None, "error": type(exc).__name__ + ": " + str(exc)}


def emit(result):
    print("GPU_SMOKE_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result.get("status") in {"PASS", "CPU_ONLY_PASS"} else 1


def main():
    started = time.time()
    result = {"worker_digest": EXPECTED_DIGEST, "entrypoint": str(Path(__file__))}
    try:
        if os.environ.get("GPU_SMOKE_CPU_ONLY") == "1":
            preflight = run_preflight()
            result.update(
                {
                    "status": "CPU_ONLY_PASS",
                    "reason": "CPU-only entrypoint reached; CUDA absence is expected",
                    "preflight": preflight,
                }
            )
            return emit(result)

        preflight = run_preflight()
        result["preflight"] = preflight
        if preflight.get("exit_code") != 0:
            raise RuntimeError("cuda_runtime_preflight failed")

        import cv2
        import numpy as np
        import torch

        result["cuda_available"] = bool(torch.cuda.is_available())
        result["cuda_device_count"] = int(torch.cuda.device_count())
        result["cuda_version"] = torch.version.cuda
        if not result["cuda_available"]:
            raise RuntimeError("CUDA unavailable")
        result["gpu_name"] = torch.cuda.get_device_name(0)
        x = torch.randn((1024, 1024), device="cuda")
        y = torch.mm(x, x)
        torch.cuda.synchronize()
        result["cuda_matmul_finite"] = bool(torch.isfinite(y).all().item())
        result["cuda_peak_mb"] = round(torch.cuda.max_memory_allocated() / 1024**2, 2)

        sys.path.insert(0, "/workspace/project")
        from src.infrastructure.processors.rife.native import RIFENative
        from src.infrastructure.processors.realesrgan.native import RealESRGANNative

        with tempfile.TemporaryDirectory(prefix="aividup-gpu-smoke-") as tmp:
            root = Path(tmp)
            frames = root / "frames"
            frames.mkdir()
            for i in range(3):
                image = np.zeros((128, 128, 3), dtype=np.uint8)
                cv2.rectangle(
                    image, (12 + i * 20, 32), (52 + i * 20, 72), (0, 200, 255), -1
                )
                cv2.circle(image, (64, 96), 18, (255, 80, 20), -1)
                cv2.imwrite(str(frames / f"frame_{i:06d}.png"), image)
            input_frames = sorted(frames.glob("*.png"))

            out48 = RIFENative(factor=2.0, device="cuda").process_frames_to_fps(
                input_frames, root / "rife48", 24.0, 48.0
            )
            out60 = RIFENative(factor=2.0, device="cuda").process_frames_to_fps(
                input_frames, root / "rife60", 24.0, 60.0
            )
            result["rife_24_to_48_frames"] = len(out48)
            result["rife_24_to_60_frames"] = len(out60)
            result["rife_pass"] = len(out48) == 6 and len(out60) == 8
            mid = cv2.imread(str(out60[1]))
            first = cv2.imread(str(input_frames[0]))
            second = cv2.imread(str(input_frames[1]))
            result["rife_intermediate_changed"] = bool(
                np.mean(cv2.absdiff(mid, first)) > 0
                and np.mean(cv2.absdiff(mid, second)) > 0
            )

            upscale = {}
            for scale in (2, 4):
                out = RealESRGANNative(
                    scale=scale, tile_size=64, half=True, device="cuda"
                ).process_frames([input_frames[0]], root / f"realesrgan_x{scale}")
                image = cv2.imread(str(out[0]), cv2.IMREAD_COLOR)
                key = f"realesrgan_x{scale}"
                upscale[key] = {
                    "width": int(image.shape[1]),
                    "height": int(image.shape[0]),
                    "pass": bool(
                        image.shape[1] == 128 * scale and image.shape[0] == 128 * scale
                    ),
                }
            result["realesrgan"] = upscale
            result["realesrgan_pass"] = all(v["pass"] for v in upscale.values())
            result["peak_vram_mb"] = round(
                torch.cuda.max_memory_allocated() / 1024**2, 2
            )
            result["status"] = (
                "PASS"
                if result["cuda_matmul_finite"]
                and result["rife_pass"]
                and result["rife_intermediate_changed"]
                and result["realesrgan_pass"]
                else "FAIL"
            )
            if result["status"] == "FAIL":
                result["reason"] = "one or more inference assertions failed"
    except Exception as exc:
        result["status"] = "FAIL"
        result["reason"] = type(exc).__name__ + ": " + str(exc)
        result["traceback"] = traceback.format_exc()
    finally:
        result["elapsed_seconds"] = round(time.time() - started, 3)
    return emit(result)


if __name__ == "__main__":
    raise SystemExit(main())
