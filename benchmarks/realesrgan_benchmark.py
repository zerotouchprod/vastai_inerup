#!/usr/bin/env python3
"""Reproducible, local-only Real-ESRGAN benchmark harness.

No provider API is called. The harness requires an already provisioned CUDA host and
writes one JSON record per case. It intentionally does not download weights.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("input_dir", type=Path)
    p.add_argument("output_jsonl", type=Path)
    p.add_argument("--model", choices=["RealESRGAN_x2plus", "RealESRGAN_x4plus", "realesr-general-x4v3"], required=True)
    p.add_argument("--output-scale", type=int, choices=[2, 4], required=True)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--tile-size", type=int, default=0)
    p.add_argument("--no-half", action="store_true")
    p.add_argument("--cudnn-benchmark", action="store_true")
    p.add_argument("--channels-last", action="store_true")
    p.add_argument("--compile", action="store_true")
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--limit", type=int, default=0)
    return p.parse_args()


def gpu_snapshot(torch):
    if not torch.cuda.is_available():
        return {"cuda": False}
    d = torch.cuda.current_device()
    p = torch.cuda.get_device_properties(d)
    return {
        "cuda": True,
        "device": torch.cuda.get_device_name(d),
        "vram_total_bytes": p.total_memory,
        "vram_allocated_bytes": torch.cuda.memory_allocated(d),
        "vram_reserved_bytes": torch.cuda.memory_reserved(d),
    }


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import cv2
    import numpy as np
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this benchmark; no GPU is rented by this script")
    if args.cudnn_benchmark:
        torch.backends.cudnn.benchmark = True

    from realesrgan_batch_upscale import load_model

    frames = sorted(args.input_dir.glob("frame_*.png"))
    if args.limit:
        frames = frames[: args.limit]
    if not frames:
        raise SystemExit(f"No frame_*.png files in {args.input_dir}")

    network_scale = 4 if args.model == "realesr-general-x4v3" else args.output_scale
    upsampler = load_model(
        args.model,
        scale=network_scale,
        device="cuda",
        tile_size=args.tile_size,
        half=not args.no_half,
        allow_data_parallel=False,
        gpu_id=0,
    )
    if upsampler is None:
        raise SystemExit("model could not be loaded")
    if args.channels_last:
        upsampler.model = upsampler.model.to(memory_format=torch.channels_last)
    if args.compile:
        upsampler.model = torch.compile(upsampler.model)

    def forward(imgs):
        batch = np.stack([cv2.cvtColor(x, cv2.COLOR_BGR2RGB).transpose(2, 0, 1) for x in imgs])
        x = torch.from_numpy(batch).to("cuda", non_blocking=True).float().div_(255)
        if not args.no_half:
            x = x.half()
        if args.channels_last:
            x = x.to(memory_format=torch.channels_last)
        with torch.inference_mode():
            y = upsampler.model(x)
        y = y.float().clamp_(0, 1).cpu().numpy()
        out = []
        for item in y:
            bgr = (item.transpose(1, 2, 0)[:, :, ::-1] * 255).round().astype(np.uint8)
            if network_scale != args.output_scale:
                h, w = bgr.shape[:2]
                bgr = cv2.resize(bgr, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
            out.append(bgr)
        return out

    first = cv2.imread(str(frames[0]), cv2.IMREAD_COLOR)
    for _ in range(max(0, args.warmup)):
        forward([first] * args.batch_size)
    torch.cuda.synchronize()
    started = time.perf_counter()
    processed = 0
    for i in range(0, len(frames), args.batch_size):
        imgs = [cv2.imread(str(p), cv2.IMREAD_COLOR) for p in frames[i : i + args.batch_size]]
        forward(imgs)
        processed += len(imgs)
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    record = {
        "model": args.model,
        "network_scale": network_scale,
        "output_scale": args.output_scale,
        "frames": processed,
        "fps": processed / elapsed if elapsed else 0,
        "elapsed_s": elapsed,
        "batch_size": args.batch_size,
        "tile_size": args.tile_size,
        "fp16": not args.no_half,
        "cudnn_benchmark": args.cudnn_benchmark,
        "channels_last": args.channels_last,
        "torch_compile": args.compile,
        "gpu": gpu_snapshot(torch),
    }
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.output_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
