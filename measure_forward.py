#!/usr/bin/env python3
"""Quick forward profiler for Real-ESRGAN model used in the pipeline.
Usage:
  python3 measure_forward.py --model RealESRGAN_x2plus --scale 2 --n 8 --h 1080 --w 1920
"""
import time
import argparse
import torch

from realesrgan_batch_upscale import load_model

parser = argparse.ArgumentParser()
parser.add_argument('--model', default='RealESRGAN_x2plus')
parser.add_argument('--scale', type=int, default=2)
parser.add_argument('--n', type=int, default=8, help='number of images in synthetic batch')
parser.add_argument('--h', type=int, default=1080)
parser.add_argument('--w', type=int, default=1920)
parser.add_argument('--half', action='store_true')
parser.add_argument('--device', default='cuda')
args = parser.parse_args()

print('Loading model...')
upsampler = load_model(args.model, args.scale, device=args.device, tile_size=512, half=args.half, allow_data_parallel=False, gpu_id=0)
if upsampler is None:
    raise SystemExit('Failed to load model')

dtype = torch.half if (args.half and torch.cuda.is_available()) else torch.float
N = args.n
H = args.h
W = args.w
print(f'Creating synthetic batch N={N} HxW={H}x{W} dtype={dtype} on {args.device}')

a = torch.randn(N, 3, H, W, dtype=dtype, device='cuda' if args.device=='cuda' else 'cpu')
# warmup
with torch.no_grad():
    for _ in range(2):
        out = upsampler.model(a[:max(1, min(N,2))])
        if args.device == 'cuda':
            torch.cuda.synchronize()

# measure several repeats
repeats = 3
times = []
with torch.no_grad():
    for r in range(repeats):
        t0 = time.time()
        out = upsampler.model(a)
        if args.device == 'cuda':
            torch.cuda.synchronize()
        dt = time.time() - t0
        times.append(dt)
        print(f'Iter {r+1}/{repeats}: batch_forward_time={dt:.3f}s, per_frame={dt/ N:.3f}s')

best = min(times)
avg = sum(times)/len(times)
print(f'Best: {best:.3f}s (per-frame {best/N:.3f}s), Avg: {avg:.3f}s')
print('Done')

