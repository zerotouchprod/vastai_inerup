#!/usr/bin/env python3
"""Fail-closed CUDA and production-backend runtime certification probe."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


def fail(reason: str, **extra: object) -> None:
    payload = {"decision": "DENY", "reason": reason, **extra}
    print("CUDA_RUNTIME_PREFLIGHT_FAIL " + json.dumps(payload, sort_keys=True), flush=True)
    raise SystemExit(42)


def main() -> int:
    try:
        import torch
    except Exception as exc:  # pragma: no cover - exercised in image
        fail("torch_import_failed", error=str(exc))

    evidence: dict[str, object] = {
        "torch_version": str(torch.__version__),
        "torch_cuda": str(torch.version.cuda),
    }
    try:
        if not torch.cuda.is_available():
            fail("cuda_unavailable", **evidence)
        if torch.cuda.device_count() < 1:
            fail("cuda_device_missing", **evidence)
        device = torch.device("cuda:0")
        evidence.update(
            {
                "gpu_name": torch.cuda.get_device_name(0),
                "compute_capability": list(torch.cuda.get_device_capability(0)),
                "arch_list": list(torch.cuda.get_arch_list()),
            }
        )
        x = torch.randn(16, 16, device=device)
        _ = x @ x
        torch.cuda.synchronize()
    except SystemExit:
        raise
    except Exception as exc:
        fail("cuda_tensor_probe_failed", error=str(exc), **evidence)

    backend = os.environ.get("AIVIDUP_GPU_PROBE_BACKEND", "realesrgan").strip().lower()
    if backend == "realesrgan":
        try:
            import cv2
            import numpy as np
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

            weights = Path(
                os.environ.get(
                    "AIVIDUP_REALESRGAN_WEIGHTS",
                    "/opt/realesrgan_models/RealESRGAN_x2plus.pth",
                )
            )
            if not weights.is_file():
                fail("realesrgan_weights_missing", weights=str(weights), **evidence)
            model = RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=2,
            )
            upsampler = RealESRGANer(
                scale=2,
                model_path=str(weights),
                model=model,
                tile=0,
                tile_pad=10,
                pre_pad=0,
                half=True,
            )
            frame = np.zeros((16, 16, 3), dtype=np.uint8)
            output, _ = upsampler.enhance(frame, outscale=2)
            if output is None or output.size == 0:
                fail("realesrgan_inference_empty", **evidence)
            torch.cuda.synchronize()
            evidence["backend"] = "realesrgan"
            evidence["backend_probe_shape"] = list(output.shape)
        except SystemExit:
            raise
        except Exception as exc:
            fail("realesrgan_probe_failed", error=str(exc), **evidence)
    elif backend == "rife":
        try:
            import cv2
            import numpy as np
            from src.infrastructure.processors.rife.native import RIFENative

            with tempfile.TemporaryDirectory(prefix="aividup-rife-probe-") as tmp:
                root = Path(tmp)
                first = root / "000000.png"
                second = root / "000001.png"
                frame = np.zeros((64, 64, 3), dtype=np.uint8)
                cv2.imwrite(str(first), frame)
                cv2.imwrite(str(second), frame)
                output = RIFENative(factor=2, device="cuda").process_frames(
                    [first, second], root / "out"
                )
                if not output:
                    fail("rife_inference_empty", **evidence)
            torch.cuda.synchronize()
            evidence["backend"] = "rife"
            evidence["backend_probe_frames"] = len(output)
        except SystemExit:
            raise
        except Exception as exc:
            fail("rife_probe_failed", error=str(exc), **evidence)
    else:
        fail("unknown_probe_backend", backend=backend, **evidence)

    evidence["decision"] = "ALLOW"
    print("CUDA_RUNTIME_PREFLIGHT_PASS " + json.dumps(evidence, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
