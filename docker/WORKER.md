# AIVIDUP GPU worker image

`docker/Dockerfile.worker` → pull worker for the chunked pipeline (upscale + interpolation). Lean on purpose: CUDA 12.6 runtime,
PyTorch 2.9.1, Real-ESRGAN, RIFE v4.26, ffmpeg. **No** OCR / SAM2 / ProPainter (the legacy `Dockerfile.pytorch.fat` keeps those for
subtitle/watermark removal; ProPainter's licence is non-commercial, so it stays out of the paid worker).
Code and weights are baked in and pinned to the build (`/etc/aividup_revision`); there is no `git pull` at start.

## Build
```bash
scripts/build_worker.sh                 # ghcr.io/zerotouchprod/aividup-worker:<git-sha>
PUSH=1 scripts/build_worker.sh          # + push (docker login ghcr.io first)
```
The build ends with an import smoke test (torch, basicsr, realesrgan, the worker, the pipeline CLI), so a broken dependency fails the
build, not a rented GPU. CI: `.github/workflows/build-worker.yml` (manual, or on changes to the worker files). Pin the exact SHA tag in the
control plane; never `:latest`.

## Run
| env | |
|---|---|
| `AIVIDUP_API_URL` | **required**, e.g. `https://aividup.com/api/worker` |
| `AIVIDUP_WORKER_TOKEN` | **required**, same value as the control plane's `PROCESSING_WORKER_TOKEN` (env only, never on a command line) |
| `AIVIDUP_WORKER_ID` | defaults to Vast's `CONTAINER_ID`. **Must equal the `GpuLease` instance id**: a worker only claims tasks of its own instance |
| `AIVIDUP_PROCESSOR` | `pipeline` (GPU, default) · `ffmpeg` (CPU stand-in) · `passthrough` |
| `AIVIDUP_IDLE_EXIT_SECONDS` | 300 - exit when idle (stop paying for an idle GPU) |
| `AIVIDUP_MAX_LIFETIME_SECONDS` | 14400 - hard cap |
| `AIVIDUP_MAX_RESTARTS` | 5 - crash restarts (a restarted worker resumes the attempt it owns) before giving up (exit 4) |
| `AIVIDUP_SELF_DESTROY=1` | after exit, destroy this Vast instance (`CONTAINER_ID` + `CONTAINER_API_KEY`); best effort, the control plane's lease reaper stays authoritative |

Startup: validates config, refuses to take work if PyTorch cannot really use the GPU (exit 3: bad host), then supervises `python -m src.worker`
(restart on crash, process-group cleanup so no orphan runs beside its replacement, SIGTERM exits 143 without self-destroy).

Local smoke without a GPU (CPU stand-in processor, against a dev control plane):
```bash
AIVIDUP_API_URL=http://127.0.0.1:8081/api/worker AIVIDUP_WORKER_TOKEN=... AIVIDUP_WORKER_ID=ok-1 AIVIDUP_PROCESSOR=ffmpeg bash scripts/worker_start.sh
```

## Verified vs. not
**Verified on a real build of this Dockerfile** (CUDA-less builder, CPU runs inside the container, 2026-10):
- the image builds end to end (26 steps, 10.6 GB, torch 2.9.1+cu126, ffmpeg 4.4.2) and the build-time import smoke test passes;
- `worker_start.sh` inside the container: config validation (exit 2), dry run, token never printed; weights present (Real-ESRGAN x2/x4, RIFE v4.26);
- Real-ESRGAN x2 on CPU: 48x64 -> 96x128 (validates the basicsr patch, weights and torchvision compatibility);
- fractional RIFE (`process_frames_to_fps`) on the real v4.26 weights, CPU: 24 -> 60 fps gives exactly the planned frame count, originals bit-exact, and the
  synthesised frames are real motion-compensated interpolation (PSNR vs. ground-truth middle frame 24.5 dB vs. 21.9 dB for naive blending; timestep monotonic);
- the containerised worker against a live control plane over HTTP: claim, heartbeat, deliver, report; job completed at 60 fps with audio, credits charged once.
`worker_start.sh` itself: 19 behavioural tests (config, id resolution, restart, orphan cleanup, SIGTERM, lifetime cap, self-destroy) plus `kill -9` of the worker mid-job.

**Not verified - needs a real GPU machine:** CUDA execution of RIFE / Real-ESRGAN (speed, VRAM, `half`), chunk seams at 60 fps on real footage, that Vast injects
`CONTAINER_ID` / `CONTAINER_API_KEY` and honours the image entrypoint for `runtype=args`, image pull time (10.6 GB).

## Known limits / ideas
- No `h264_nvenc` in the apt ffmpeg (the assembler falls back to libx264 automatically). A static ffmpeg build would enable GPU encoding.
- Image size: the CUDA base (~3 GB) duplicates libraries that the torch wheels already bundle; a plain `ubuntu:22.04` base would save ~3 GB of pull time.
- Building inside a sandbox that re-terminates TLS needs the proxy CA inside the build (test-only copy of the Dockerfile; the real one is unchanged).
