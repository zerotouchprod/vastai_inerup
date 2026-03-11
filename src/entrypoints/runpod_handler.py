#!/usr/bin/env python3
"""
RunPod Serverless Handler — HunyuanVideo Pure Text-to-Video

Pipeline:
  Phase 1 │ HunyuanVideo T2V │ prompt → /tmp/video_<id>.mp4
  Phase 2 │ Cloudflare R2    │ upload → presigned URL (24h)

VRAM budget (RTX 4090, 24 GB):
  HunyuanVideo bfloat16 + cpu_offload + vae.tiling ≈ 22 GB peak
"""

from __future__ import annotations

import gc
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import torch
from diffusers.utils import export_to_video

import runpod
from src.shared.logging import get_logger

logger = get_logger(__name__)

# ── Volume / model paths ──────────────────────────────────────────────────────
_VOLUME_CANDIDATES = ["/workspace", "/runpod-volume", "/volume"]
VOLUME_BASE: str = next(
    (p for p in _VOLUME_CANDIDATES if os.path.exists(p)),
    "/workspace",
)
logger.info(f"✅ Found Network Volume at: {VOLUME_BASE}")

MODEL_PATH = os.path.join(VOLUME_BASE, "models/HunyuanVideo")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_NUM_FRAMES: int = 49    # 4k+1
DEFAULT_STEPS: int = 50
DEFAULT_GUIDANCE: float = 6.0
DEFAULT_FPS: int = 8
DEFAULT_WIDTH: int = 720
DEFAULT_HEIGHT: int = 480


# ── VRAM flush ────────────────────────────────────────────────────────────────

def flush_vram() -> None:
    """Очистить VRAM после генерации — держит warm worker чистым."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        alloc = torch.cuda.memory_allocated() / 1024 ** 3
        resv  = torch.cuda.memory_reserved()   / 1024 ** 3
        logger.info(f"VRAM after flush: {alloc:.2f} GB alloc / {resv:.2f} GB reserved")


# ── Video generation ──────────────────────────────────────────────────────────

def generate_video(
    prompt: str,
    num_inference_steps: int,
    guidance_scale: float,
    num_frames: int,
    fps: int,
    height: int,
    width: int,
    seed: Optional[int],
) -> Path:
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"HunyuanVideo model not found: {MODEL_PATH}")

    from diffusers import HunyuanVideoPipeline  # noqa: PLC0415

    import diffusers as _d  # noqa: PLC0415
    logger.info(f"diffusers: {_d.__version__}")
    logger.info(f"Loading HunyuanVideoPipeline from {MODEL_PATH}")

    pipe = HunyuanVideoPipeline.from_pretrained(
        MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )

    # CRITICAL: без cpu_offload — OOM на 24 GB
    pipe.enable_model_cpu_offload()

    # CRITICAL: VAE tiling предотвращает memory spike при декоде
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
        logger.info("VAE tiling enabled")

    if hasattr(pipe, "enable_vae_slicing"):
        pipe.enable_vae_slicing()

    # HunyuanVideo требует num_frames = 4k+1
    stf = getattr(pipe, "vae_scale_factor_temporal", 4)
    corrected = max(1, ((num_frames - 1) // stf) * stf + 1)
    if corrected != num_frames:
        logger.warning(f"num_frames {num_frames} → {corrected} (4k+1, temporal={stf})")
        num_frames = corrected

    generator = torch.Generator("cpu").manual_seed(seed) if seed is not None else None

    logger.info(f"Generating {num_frames} frames  steps={num_inference_steps}  cfg={guidance_scale}  {width}x{height}  fps={fps}")

    try:
        with torch.inference_mode():
            output = pipe(
                prompt=prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                num_frames=num_frames,
                height=height,
                width=width,
                generator=generator,
            )
        frames = output.frames[0]
    finally:
        del pipe
        flush_vram()

    out = Path("/tmp") / f"video_{uuid.uuid4().hex[:8]}.mp4"
    export_to_video(frames, str(out), fps=fps)
    logger.info(f"✓ Video: {out}  ({out.stat().st_size / 1024 ** 2:.1f} MB)")
    return out


# ── RunPod job handler ────────────────────────────────────────────────────────

def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input: dict[str, Any] = job.get("input", {})
    job_id: str = job.get("id", str(uuid.uuid4()))
    logger.info(f"Processing job {job_id}")
    logger.info(f"Job input: {json.dumps(job_input, indent=2)}")

    try:
        # ── Prompt ───────────────────────────────────────────────────────────
        prompt: str = job_input.get("prompt", "")
        if not prompt:
            raise ValueError("'prompt' is required")

        seed: Optional[int] = job_input.get("seed")

        # ── Generation params ─────────────────────────────────────────────────
        num_inference_steps: int = job_input.get("num_inference_steps", DEFAULT_STEPS)
        guidance_scale: float    = job_input.get("guidance_scale", DEFAULT_GUIDANCE)
        fps: int                 = job_input.get("fps", DEFAULT_FPS)
        height: int              = job_input.get("height", DEFAULT_HEIGHT)
        width: int               = job_input.get("width", DEFAULT_WIDTH)

        raw_frames: int = job_input.get("num_frames", DEFAULT_NUM_FRAMES)
        num_frames: int = max(1, ((raw_frames - 1) // 4) * 4 + 1)
        if num_frames != raw_frames:
            logger.warning(f"num_frames {raw_frames} → {num_frames} (4k+1)")

        # ── Generate ──────────────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("HunyuanVideo Text-to-Video Generation")
        logger.info(f"  prompt: {prompt[:120]}")
        logger.info(f"  steps={num_inference_steps}  cfg={guidance_scale}  frames={num_frames}  fps={fps}")
        logger.info("=" * 60)

        video_path = generate_video(
            prompt=prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            num_frames=num_frames,
            fps=fps,
            height=height,
            width=width,
            seed=seed,
        )

        # ── R2 upload ─────────────────────────────────────────────────────────
        video_url: Optional[str] = None
        r2_key: Optional[str] = None

        if all([os.getenv("R2_ACCESS_KEY_ID"), os.getenv("R2_SECRET_ACCESS_KEY"),
                os.getenv("R2_BUCKET"), os.getenv("R2_ENDPOINT")]):
            try:
                from src.infrastructure.storage.r2_client import R2Client  # noqa: PLC0415
                r2 = R2Client()
                r2_key = f"outputs/{job_id}/{video_path.name}"
                r2.upload_file(video_path, r2_key)
                video_url = r2.get_presigned_url(r2_key, expires_in=86400)
                video_path.unlink(missing_ok=True)
                logger.info(f"✅ Uploaded to R2: {r2_key}")
            except Exception as exc:
                logger.warning(f"⚠️ R2 upload failed (non-fatal): {exc}")
        else:
            logger.warning("⚠️ R2 not configured — skipping upload")

        logger.info(f"✅ Job {job_id} completed")
        return {
            "status": "success",
            "job_id": job_id,
            "video_url": video_url,
            "video_path": str(video_path),
            "r2_key": r2_key,
            "prompt": prompt,
            "parameters": {
                "num_inference_steps": num_inference_steps,
                "guidance_scale": guidance_scale,
                "num_frames": num_frames,
                "fps": fps,
                "height": height,
                "width": width,
                "seed": seed,
            },
        }

    except Exception as exc:
        logger.error(f"❌ Job {job_id} failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "job_id": job_id,
            "error": str(exc),
            "prompt": job_input.get("prompt", ""),
        }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 60)
    logger.info("RunPod Serverless — HunyuanVideo T2V")
    logger.info("=" * 60)
    logger.info(f"Model     : {MODEL_PATH}")
    logger.info(f"HF_HUB_OFFLINE: {os.getenv('HF_HUB_OFFLINE', 'NOT SET')}")
    logger.info(f"CUDA      : {torch.cuda.is_available()}")
    logger.info("=" * 60)

    if not os.path.exists(MODEL_PATH):
        logger.error(f"❌ Model not found: {MODEL_PATH}")
        sys.exit(1)

    runpod.serverless.start({"handler": process_job})


if __name__ == "__main__":
    main()

