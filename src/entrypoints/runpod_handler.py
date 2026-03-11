"""
RunPod Serverless Handler — FLUX.1-schnell T2I + HunyuanVideo I2V

Pipeline:
  Phase 1 │ FLUX.1-schnell      │ t2i_prompt → /tmp/ref_<id>.png
  Phase 2 │ HunyuanVideo I2V    │ i2v_prompt + ref image → /tmp/video_<id>.mp4
  Phase 3 │ Cloudflare R2       │ upload → presigned URL (24 h)

VRAM budget (RTX 4090, 24 GB):
  FLUX  bfloat16 + cpu_offload  ≈ 20 GB peak  (flushed before Phase 2)
  Hunyuan bfloat16 + cpu_offload + vae.tiling ≈ 22 GB peak
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
from PIL import Image
from diffusers.utils import export_to_video

import runpod

from src.shared.logging import get_logger

logger = get_logger(__name__)

# ── Volume paths ──────────────────────────────────────────────────────────────
_VOLUME_CANDIDATES = ["/workspace", "/runpod-volume", "/volume"]
VOLUME_BASE: str = next(
    (p for p in _VOLUME_CANDIDATES if os.path.exists(p)),
    "/workspace",
)
logger.info(f"Network Volume: {VOLUME_BASE}")

T2I_MODEL_PATH = os.path.join(VOLUME_BASE, "models/FLUX.1-schnell")
I2V_MODEL_PATH = os.path.join(VOLUME_BASE, "models/HunyuanVideo")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_T2I_STEPS: int = 4          # FLUX.1-schnell оптимум
DEFAULT_T2I_GUIDANCE: float = 0.0   # schnell — distilled, CFG не нужен
DEFAULT_T2I_MAX_SEQ: int = 256
DEFAULT_I2V_STEPS: int = 50
DEFAULT_I2V_GUIDANCE: float = 6.0
DEFAULT_NUM_FRAMES: int = 61        # 4k+1
DEFAULT_FPS: int = 8
I2V_WIDTH: int = 720
I2V_HEIGHT: int = 480


# ── VRAM flush ────────────────────────────────────────────────────────────────

def flush_vram() -> None:
    """Полностью очистить VRAM между фазами — КРИТИЧНО для 24 GB GPU."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
        alloc = torch.cuda.memory_allocated() / 1024 ** 3
        resv = torch.cuda.memory_reserved() / 1024 ** 3
        logger.info(f"VRAM after flush: {alloc:.2f} GB alloc / {resv:.2f} GB reserved")


# ── Phase 1: FLUX.1-schnell T2I ──────────────────────────────────────────────

def generate_image(
    prompt: str,
    negative_prompt: Optional[str],  # FLUX schnell ignores it, kept for API compat
    num_inference_steps: int,
    guidance_scale: float,
    max_sequence_length: int,
    seed: Optional[int],
) -> Path:
    if not os.path.exists(T2I_MODEL_PATH):
        raise FileNotFoundError(f"T2I model not found: {T2I_MODEL_PATH}")

    from diffusers import FluxPipeline  # noqa: PLC0415

    logger.info(f"Loading FluxPipeline from {T2I_MODEL_PATH}")
    pipe = FluxPipeline.from_pretrained(
        T2I_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    # CRITICAL: cpu_offload — FLUX text encoders alone are ~12 GB
    pipe.enable_model_cpu_offload()

    generator = torch.Generator("cpu").manual_seed(seed) if seed is not None else None

    try:
        with torch.inference_mode():
            image: Image.Image = pipe(
                prompt=prompt,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps,
                max_sequence_length=max_sequence_length,
                width=I2V_WIDTH,
                height=I2V_HEIGHT,
                generator=generator,
            ).images[0]
    finally:
        del pipe
        flush_vram()

    out = Path("/tmp") / f"ref_{uuid.uuid4().hex[:8]}.png"
    image.save(out)
    logger.info(f"✓ Reference image saved: {out}  size={image.size}")
    return out


# ── Phase 2: HunyuanVideo I2V ─────────────────────────────────────────────────

def generate_video(
    image_path: Path,
    prompt: str,
    negative_prompt: Optional[str],
    num_inference_steps: int,
    guidance_scale: float,
    num_frames: int,
    fps: int,
    seed: Optional[int],
) -> Path:
    if not os.path.exists(I2V_MODEL_PATH):
        raise FileNotFoundError(f"I2V model not found: {I2V_MODEL_PATH}")

    # diffusers>=0.33 ships HunyuanVideoImageToVideoPipeline
    HunyuanVideoImageToVideoPipeline: type | None = None
    try:
        from diffusers import HunyuanVideoImageToVideoPipeline  # type: ignore[assignment]  # noqa: PLC0415
        pipeline_cls = HunyuanVideoImageToVideoPipeline
        logger.info("Using HunyuanVideoImageToVideoPipeline")
    except ImportError:
        from diffusers import HunyuanVideoPipeline  # noqa: PLC0415
        pipeline_cls = HunyuanVideoPipeline
        logger.warning("HunyuanVideoImageToVideoPipeline not available — falling back to T2V HunyuanVideoPipeline")

    import diffusers as _d  # noqa: PLC0415
    logger.info(f"diffusers: {_d.__version__}")

    logger.info(f"Loading {pipeline_cls.__name__} from {I2V_MODEL_PATH}")
    pipe = pipeline_cls.from_pretrained(
        I2V_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )

    # CRITICAL: without cpu_offload HunyuanVideo will OOM on 24 GB
    pipe.enable_model_cpu_offload()

    # CRITICAL: VAE tiling reduces peak VRAM during decode
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
        logger.info("VAE tiling enabled")

    if hasattr(pipe, "enable_vae_slicing"):
        pipe.enable_vae_slicing()

    stf = getattr(pipe, "vae_scale_factor_temporal", 4)

    try:
        image = Image.open(image_path).convert("RGB")
        if image.size != (I2V_WIDTH, I2V_HEIGHT):
            logger.warning(f"Resizing {image.size} → ({I2V_WIDTH}, {I2V_HEIGHT})")
            image = image.resize((I2V_WIDTH, I2V_HEIGHT), Image.LANCZOS)

        # HunyuanVideo requires num_frames = 4k+1
        corrected = max(1, ((num_frames - 1) // stf) * stf + 1)
        if corrected != num_frames:
            logger.warning(f"num_frames {num_frames} → {corrected} (temporal={stf})")
            num_frames = corrected

        generator = torch.Generator("cpu").manual_seed(seed) if seed is not None else None
        logger.info(f"Generating {num_frames} frames  steps={num_inference_steps}  cfg={guidance_scale}  fps={fps}")

        is_i2v = HunyuanVideoImageToVideoPipeline is not None and isinstance(pipe, HunyuanVideoImageToVideoPipeline)
        call_kwargs: dict[str, Any] = dict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            num_frames=num_frames,
            height=I2V_HEIGHT,
            width=I2V_WIDTH,
            generator=generator,
        )
        if is_i2v:
            call_kwargs["image"] = image

        with torch.inference_mode():
            output = pipe(**call_kwargs)

        frames = output.frames[0]

    finally:
        del pipe
        flush_vram()

    out = Path("/tmp") / f"video_{uuid.uuid4().hex[:8]}.mp4"
    export_to_video(frames, str(out), fps=fps)
    logger.info(f"✓ Video saved: {out}  ({out.stat().st_size / 1024 ** 2:.1f} MB)")
    return out


# ── RunPod handler ────────────────────────────────────────────────────────────

def process_job(job: dict[str, Any]) -> dict[str, Any]:
    job_input: dict[str, Any] = job.get("input", {})
    job_id: str = job.get("id", str(uuid.uuid4()))
    logger.info(f"Job {job_id}\n{json.dumps(job_input, indent=2)}")

    try:
        # ── Prompts (FLUX uses natural language, no tag soup needed) ─────────
        base: str = job_input.get("prompt", "")
        t2i_prompt: str = job_input.get("t2i_prompt") or base
        i2v_prompt: str = job_input.get("i2v_prompt") or base

        if not t2i_prompt:
            raise ValueError("t2i_prompt (or prompt) is required")
        if not i2v_prompt:
            raise ValueError("i2v_prompt (or prompt) is required")

        negative_prompt: Optional[str] = job_input.get("negative_prompt")
        seed: Optional[int] = job_input.get("seed")

        # T2I
        t2i_steps: int = job_input.get("t2i_steps", DEFAULT_T2I_STEPS)
        t2i_guidance: float = job_input.get("t2i_guidance_scale", DEFAULT_T2I_GUIDANCE)
        t2i_max_seq: int = job_input.get("max_sequence_length", DEFAULT_T2I_MAX_SEQ)

        # I2V
        i2v_steps: int = job_input.get("num_inference_steps", DEFAULT_I2V_STEPS)
        i2v_guidance: float = job_input.get("guidance_scale", DEFAULT_I2V_GUIDANCE)
        fps: int = job_input.get("fps", DEFAULT_FPS)
        raw_frames: int = job_input.get("num_frames", DEFAULT_NUM_FRAMES)
        num_frames: int = max(1, ((raw_frames - 1) // 4) * 4 + 1)
        if num_frames != raw_frames:
            logger.warning(f"num_frames {raw_frames} → {num_frames} (4k+1)")

        # ── Phase 1 ──────────────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("PHASE 1: FLUX.1-schnell Text-to-Image")
        logger.info(f"  prompt : {t2i_prompt[:120]}")
        logger.info(f"  steps={t2i_steps}  cfg={t2i_guidance}  max_seq={t2i_max_seq}")
        logger.info("=" * 60)

        image_path = generate_image(
            prompt=t2i_prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=t2i_steps,
            guidance_scale=t2i_guidance,
            max_sequence_length=t2i_max_seq,
            seed=seed,
        )

        # ── Phase 2 ──────────────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("PHASE 2: HunyuanVideo Image-to-Video")
        logger.info(f"  prompt : {i2v_prompt[:120]}")
        logger.info(f"  steps={i2v_steps}  cfg={i2v_guidance}  frames={num_frames}  fps={fps}")
        logger.info("=" * 60)

        video_path = generate_video(
            image_path=image_path,
            prompt=i2v_prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=i2v_steps,
            guidance_scale=i2v_guidance,
            num_frames=num_frames,
            fps=fps,
            seed=seed,
        )

        image_path.unlink(missing_ok=True)

        # ── Phase 3: R2 upload ───────────────────────────────────────────────
        video_url: Optional[str] = None
        r2_key: Optional[str] = None

        r2_cfg = {
            "access_key_id": os.getenv("R2_ACCESS_KEY_ID"),
            "secret_access_key": os.getenv("R2_SECRET_ACCESS_KEY"),
            "bucket": os.getenv("R2_BUCKET"),
            "endpoint_url": os.getenv("R2_ENDPOINT"),
        }

        if all(r2_cfg.values()):
            try:
                from src.infrastructure.storage.r2_client import R2Client  # noqa: PLC0415
                r2 = R2Client(
                    **r2_cfg,
                    region=os.getenv("R2_DEFAULT_REGION", "auto"),
                )
                r2_key = f"videos/{job_id}.mp4"
                r2.upload_file(str(video_path), r2_key)
                video_url = r2.get_presigned_url(r2_key, expires_in=86400)
                video_path.unlink(missing_ok=True)
                logger.info(f"✅ R2 upload: {r2_key}")
            except Exception as exc:
                logger.warning(f"R2 upload failed (non-fatal): {exc}")
        else:
            logger.warning("R2 not configured — skipping upload")

        return {
            "status": "success",
            "job_id": job_id,
            "video_url": video_url,
            "video_path": str(video_path),
            "r2_key": r2_key,
            "t2i_prompt": t2i_prompt,
            "i2v_prompt": i2v_prompt,
            "parameters": {
                "t2i_steps": t2i_steps,
                "t2i_guidance_scale": t2i_guidance,
                "i2v_steps": i2v_steps,
                "i2v_guidance_scale": i2v_guidance,
                "num_frames": num_frames,
                "fps": fps,
                "seed": seed,
            },
        }

    except Exception as exc:
        logger.error(f"❌ Job {job_id} failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "job_id": job_id,
            "error": str(exc),
            "t2i_prompt": job_input.get("t2i_prompt", job_input.get("prompt", "")),
            "i2v_prompt": job_input.get("i2v_prompt", job_input.get("prompt", "")),
        }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("=" * 60)
    logger.info("RunPod Serverless — FLUX.1-schnell + HunyuanVideo")
    logger.info("=" * 60)
    logger.info(f"T2I: {T2I_MODEL_PATH}")
    logger.info(f"I2V: {I2V_MODEL_PATH}")
    logger.info(f"HF_HUB_OFFLINE: {os.getenv('HF_HUB_OFFLINE', 'not set')}")

    if not torch.cuda.is_available():
        logger.error("CUDA not available!")
        sys.exit(1)

    gpu = torch.cuda.get_device_name(0)
    vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
    logger.info(f"GPU: {gpu}  VRAM: {vram:.1f} GB")

    runpod.serverless.start({"handler": process_job})


if __name__ == "__main__":
    main()

