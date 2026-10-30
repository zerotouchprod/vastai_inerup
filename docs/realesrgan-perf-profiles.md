# Real-ESRGAN GPU performance profiles

Measured fastest tile/GPU-batch per **(GPU model, Real-ESRGAN model, scale, input WxH, fp16)**.
File: `src/infrastructure/processors/realesrgan/perf_profiles.yaml` (in the image),
override with `REAL_ESRGAN_PROFILES_FILE`, disable with `REAL_ESRGAN_PROFILES=off`.

| Profile | GPU | Input -> output | tile | gpu_batch | ref fps |
|---|---|---|---|---|---|
| rtx4080-x2plus-fp16-1080x1920 | RTX 4080 16GB | 1080x1920 -> 2160x3840 | 512 | 1 | 1.27 |
| rtx3090-x2plus-fp16-1080x1920 | RTX 3090 24GB | 1080x1920 -> 2160x3840 | 0 | 2 | 1.14 |

Precedence (per job/chunk, re-evaluated every `process_frames`):
1. `REAL_ESRGAN_TILE_SIZE` / `REAL_ESRGAN_BATCH_SIZE` or job `tile_size`/`batch_size`: if **either** is set, no profile applies (old behaviour).
2. Exact profile match -> profile tile + gpu_batch (beats auto-batch).
3. Otherwise unchanged: tile 0 + auto-batch from output pixels / free VRAM (#44).

Matching is exact: GPU names are normalized (`NVIDIA GeForce RTX 4080` -> `RTX 4080`), so
`RTX 4080 SUPER`/`Laptop` don't match; landscape 1920x1080 doesn't match a 1080x1920 profile.

OOM recovery is independent and starts from the profile values (batch 2 -> 1 -> tile 512;
tile 512 -> 256). Learned safe settings are scoped to one job (`begin_safe_batch_scope`):
chunks of the same job reuse them, a new job starts clean.

Telemetry: `upscale.profile_id`, `upscale.profile`, `batch_source=profile:<id>`, `tile_reason=profile:<id>`;
log line `Real-ESRGAN batch selection ... profile=<id>`.
