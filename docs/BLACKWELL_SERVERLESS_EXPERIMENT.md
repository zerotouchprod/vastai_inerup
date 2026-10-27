# Blackwell Serverless experiment

This is an isolated experiment only. It is not the production Pod worker and it does not change AIVIDUP routing.

## Artifact

- Dockerfile: `docker/Dockerfile.aividup-serverless`
- Base: `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04`
- Base amd64 digest: `sha256:59e0e4376a0f16d10b03d3a14344b80a866a1674cb4948cb318291387ac05010`
- PyTorch: `2.9.1+cu128`
- torchvision: `0.24.1+cu128`
- RunPod SDK: `1.7.13`
- Real-ESRGAN weights are verified with SHA-256 during image build.

The image build is CPU-only validation. It proves dependency installation, imports, and weight integrity; it does **not** prove CUDA inference, Blackwell compatibility, MIG behavior, NVENC, or end-to-end video processing.

## Free checks

```bash
python -m pytest -q tests/unit/test_serverless.py tests/unit/test_serverless_benchmark.py
python -m pytest -q tests/test_worker_image_contract.py
python -m compileall -q src benchmarks scripts
python benchmarks/serverless_benchmark.py --help
```

Docker build, when Docker access is available, is still a build/import check:

```bash
docker build -f docker/Dockerfile.aividup-serverless \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  -t aividup-serverless-blackwell:local .
```

No endpoint or provider API is required for these checks.

## Runtime diagnostics

The handler reports once per warm worker:

- GPU model and compute capability;
- MIG profile, if present;
- total/free VRAM;
- CUDA and PyTorch versions;
- kernel smoke result;
- NVENC real encode probe;
- selected encoder (`h264_nvenc` or `libx264`).

A MIG profile with a failed NVENC encode deliberately selects `libx264`. Merely seeing `h264_nvenc` in `ffmpeg -encoders` is not treated as proof that NVENC works.

## Benchmark contract

`benchmarks/serverless_benchmark.py` is an offline reducer. It consumes JSONL results captured from the handler; it never calls RunPod or starts a GPU. Records must use the same `input_sha256` and `input_duration_s`.

```bash
python benchmarks/serverless_benchmark.py results.jsonl \
  --rate-usd-per-hour 0.25 \
  --output summary.json
```

The reducer separates cold and warm runs and reports:

- input/download;
- setup/model loading;
- pipeline/inference;
- upload;
- total handler time;
- encoder selection;
- estimated cost from measured pipeline seconds.

The current child process exposes `input_s`, `setup_s`, `pipeline_s`, and upload/total timings. RIFE-vs-Real-ESRGAN sub-phase timings remain **NOT TESTED** until the worker emits those phase boundaries on a real GPU.

## Explicit status before paid approval

| Capability | Status |
|---|---|
| CUDA 12.8 image definition | Prepared; build not run where Docker daemon is unavailable |
| PyTorch/RIFE/Real-ESRGAN imports | Build-time check defined; GPU image build pending |
| Weight checksums | Defined and enforced during build |
| Handler contract | CPU/mock tested |
| NVENC → libx264 fallback | CPU/mock tested |
| Benchmark reducer | CPU tested |
| Blackwell CUDA inference | **NOT TESTED** |
| MIG compatibility | **NOT TESTED** |
| RIFE + Real-ESRGAN E2E | **NOT TESTED** |
| L4 vs Blackwell performance | **NOT TESTED** |
| Real provider cost | **NOT TESTED** |

No paid GPU workload is part of this PR. The proposed $2 experiment requires a separate approval after CI and review.
