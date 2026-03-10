#!/usr/bin/env python3
"""
RunPod Serverless Handler for Ultra-Fast Video Generation

This handler processes video generation jobs with zero model downloading.
Models are loaded from a mounted network volume at /workspace/models/
with HF_HUB_OFFLINE=1 to prevent any internet connection attempts.

Cold start: <5 seconds when Docker image is cached on RunPod host.
"""

import os
import sys
import json
import gc
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
from PIL import Image
from diffusers import StableDiffusionXLPipeline, CogVideoXImageToVideoPipeline
from diffusers.utils import export_to_video

import runpod
from src.shared.logging import get_logger
from src.infrastructure.storage.r2_client import R2Client

# Configure logging
logger = get_logger(__name__)

# Model paths (mounted from RunPod Network Volume)
# Network Volume может быть смонтирован в разных местах
POSSIBLE_VOLUME_PATHS = [
    "/workspace",      # RunPod часто монтирует сюда
    "/runpod-volume",  # Стандартный путь
    "/volume"          # Альтернативный путь
]

# Найти существующий volume
VOLUME_BASE = None
for path in POSSIBLE_VOLUME_PATHS:
    if os.path.exists(path):
        VOLUME_BASE = path
        logger.info(f"✅ Found Network Volume at: {path}")
        break

if VOLUME_BASE is None:
    logger.error("❌ Network Volume not found! Check mount points.")
    sys.exit(1)

T2I_MODEL_PATH = os.path.join(VOLUME_BASE, "models/dreamshaper-xl-lightning")
I2V_MODEL_PATH = os.path.join(VOLUME_BASE, "models/CogVideoX-5b-I2V")

# Default generation parameters
DEFAULT_T2I_STEPS = 4
DEFAULT_T2I_GUIDANCE_SCALE = 0.0
DEFAULT_I2V_STEPS = 25
DEFAULT_I2V_GUIDANCE_SCALE = 6.0
DEFAULT_NUM_FRAMES = 49  # CogVideoX требует 4k+1; 49 = дефолт модели
DEFAULT_FPS = 8


def load_t2i_pipeline() -> StableDiffusionXLPipeline:
    """
    Load Text-to-Image pipeline from local model path.
    Uses torch.float16 and variant="fp16" for memory efficiency.
    
    Returns:
        StableDiffusionXLPipeline instance
    """
    logger.info(f"Loading T2I model from: {T2I_MODEL_PATH}")
    
    if not os.path.exists(T2I_MODEL_PATH):
        raise FileNotFoundError(f"T2I model not found at {T2I_MODEL_PATH}")
    
    # Load pipeline with optimizations for serverless
    pipeline = StableDiffusionXLPipeline.from_pretrained(
        T2I_MODEL_PATH,
        torch_dtype=torch.float16,  # Use float16 for DreamShaper
        local_files_only=True,      # CRITICAL: No internet connection
        variant="fp16",             # Use fp16 variant if available
        use_safetensors=True
    )
    
    # Move to GPU
    pipeline = pipeline.to("cuda")
    
    # Apply memory optimizations
    if hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()
    
    logger.info("✓ T2I pipeline loaded (float16, VAE slicing enabled)")
    return pipeline


def load_i2v_pipeline() -> CogVideoXImageToVideoPipeline:
    """
    Load Image-to-Video pipeline from local model path.
    Uses torch.bfloat16 for CogVideoX with CPU offload.
    
    Returns:
        CogVideoXImageToVideoPipeline instance
    """
    logger.info(f"Loading I2V model from: {I2V_MODEL_PATH}")
    
    if not os.path.exists(I2V_MODEL_PATH):
        raise FileNotFoundError(f"I2V model not found at {I2V_MODEL_PATH}")
    
    # Load pipeline with optimizations for serverless
    pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
        I2V_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
        use_safetensors=True,
    )

    # enable_model_cpu_offload управляет перемещением само —
    # НЕ вызывать .to("cuda") перед ним, иначе конфликт устройств
    pipeline.enable_model_cpu_offload()

    if hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()

    if hasattr(pipeline, "enable_vae_tiling"):
        pipeline.enable_vae_tiling()

    logger.info("✓ I2V pipeline loaded (bfloat16, CPU offload, VAE slicing+tiling)")
    return pipeline


def aggressive_vram_cleanup():
    """
    Aggressively clean up VRAM between pipeline loads.
    CRITICAL for serverless to free memory for next job.
    """
    logger.info("🧹 Aggressive VRAM cleanup...")
    
    # Force Python garbage collection
    gc.collect()
    
    # Clear CUDA cache
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        
        # Log VRAM usage
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        logger.info(f"VRAM after cleanup: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved")


def generate_image(
    prompt: str,
    negative_prompt: Optional[str] = None,
    num_inference_steps: int = DEFAULT_T2I_STEPS,
    guidance_scale: float = DEFAULT_T2I_GUIDANCE_SCALE,
    seed: Optional[int] = None
) -> Path:
    """
    Generate image from text prompt.
    
    Args:
        prompt: Text prompt for image generation
        negative_prompt: Negative prompt for guidance
        num_inference_steps: Number of inference steps
        guidance_scale: Guidance scale
        seed: Random seed for reproducibility
        
    Returns:
        Path to generated image file
    """
    logger.info(f"Generating image for prompt: '{prompt[:60]}...'")
    
    # Load T2I pipeline
    t2i_pipeline = load_t2i_pipeline()
    
    try:
        # Create generator with seed if provided
        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(seed)
        
        # SDXL лучше работает на 768x512; ресайзим до 720x480 для CogVideoX
        with torch.inference_mode():
            image = t2i_pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
                width=768,
                height=512,
            ).images[0]

        # Ресайз до точного размера входа CogVideoX-5b-I2V
        image = image.resize((720, 480), Image.LANCZOS)

        # Save image to temporary file
        image_path = Path("/tmp") / f"ref_{uuid.uuid4().hex[:8]}.png"
        image.save(image_path)
        
        logger.info(f"✓ Image generated: {image_path}")
        return image_path
        
    finally:
        # CRITICAL: Clean up T2I pipeline aggressively
        del t2i_pipeline
        aggressive_vram_cleanup()


def generate_video(
    image_path: Path,
    prompt: str,
    negative_prompt: Optional[str] = None,
    num_inference_steps: int = DEFAULT_I2V_STEPS,
    guidance_scale: float = DEFAULT_I2V_GUIDANCE_SCALE,
    num_frames: int = DEFAULT_NUM_FRAMES,
    fps: int = DEFAULT_FPS,
    seed: Optional[int] = None
) -> Path:
    """
    Generate video from reference image.
    
    Args:
        image_path: Path to reference image
        prompt: Text prompt for video generation
        negative_prompt: Negative prompt for guidance
        num_inference_steps: Number of inference steps
        guidance_scale: Guidance scale
        num_frames: Number of frames to generate
        fps: Output video FPS
        seed: Random seed for reproducibility
        
    Returns:
        Path to generated video file
    """
    logger.info(f"Generating video from image: {image_path.name}")
    
    # Load I2V pipeline
    i2v_pipeline = load_i2v_pipeline()
    
    try:
        # Load reference image и гарантируем точный размер 720x480
        image = Image.open(image_path).convert("RGB")
        if image.size != (720, 480):
            logger.warning(f"⚠️ Image size {image.size} != (720, 480), resizing...")
            image = image.resize((720, 480), Image.LANCZOS)

        # Create generator with seed if provided
        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(seed)
        
        # Generate video frames
        # height=480, width=720 — единственный поддерживаемый размер CogVideoX-5b-I2V
        with torch.inference_mode():
            output = i2v_pipeline(
                image=image,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                num_frames=num_frames,
                height=480,
                width=720,
                generator=generator,
            )
        
        frames = output.frames[0]
        
        # Save video to temporary file
        video_path = Path("/tmp") / f"output_{uuid.uuid4().hex[:8]}.mp4"
        
        # Export frames to video
        export_to_video(
            frames,
            str(video_path),
            fps=fps
        )
        
        video_size_mb = video_path.stat().st_size / (1024**2)
        logger.info(f"✓ Video generated: {video_path} ({video_size_mb:.2f} MB)")
        return video_path
        
    finally:
        # CRITICAL: Clean up I2V pipeline aggressively
        del i2v_pipeline
        aggressive_vram_cleanup()


def process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main job processing function for RunPod Serverless.
    
    Args:
        job: Job dictionary from RunPod
        
    Returns:
        Result dictionary with status and video path
    """
    job_input = job.get("input", {})
    job_id = job.get("id", str(uuid.uuid4()))
    
    logger.info(f"Processing job {job_id}")
    logger.info(f"Job input: {json.dumps(job_input, indent=2)}")
    
    try:
        # Extract parameters from job input
        prompt = job_input.get("prompt", "")
        if not prompt:
            raise ValueError("Prompt is required")
        
        negative_prompt = job_input.get("negative_prompt")
        seed = job_input.get("seed")
        
        # T2I parameters
        t2i_steps = job_input.get("t2i_steps", DEFAULT_T2I_STEPS)
        t2i_guidance_scale = job_input.get("t2i_guidance_scale", DEFAULT_T2I_GUIDANCE_SCALE)

        # I2V parameters
        i2v_steps = job_input.get("num_inference_steps", DEFAULT_I2V_STEPS)
        i2v_guidance_scale = job_input.get("guidance_scale", DEFAULT_I2V_GUIDANCE_SCALE)
        fps = job_input.get("fps", DEFAULT_FPS)

        # CogVideoX требует num_frames = 4k+1 (1, 5, 9, 13, 17, 25, 33, 41, 49)
        # Автокоррекция: округляем до ближайшего допустимого значения
        raw_frames = job_input.get("num_frames", DEFAULT_NUM_FRAMES)
        num_frames = max(1, ((raw_frames - 1) // 4) * 4 + 1)
        if num_frames != raw_frames:
            logger.warning(f"⚠️ num_frames={raw_frames} не поддерживается CogVideoX, скорректировано до {num_frames} (требуется 4k+1)")

        # Phase 1: Generate image
        logger.info("=" * 60)
        logger.info("PHASE 1: Text-to-Image Generation")
        logger.info(f"Prompt: '{prompt[:60]}...'")
        logger.info(f"Steps: {t2i_steps}, Guidance: {t2i_guidance_scale}")
        logger.info("=" * 60)
        
        image_path = generate_image(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=t2i_steps,
            guidance_scale=t2i_guidance_scale,
            seed=seed
        )
        
        # Phase 2: Generate video
        logger.info("=" * 60)
        logger.info("PHASE 2: Image-to-Video Animation")
        logger.info(f"Steps: {i2v_steps}, Guidance: {i2v_guidance_scale}")
        logger.info(f"Frames: {num_frames}, FPS: {fps}")
        logger.info("=" * 60)
        
        video_path = generate_video(
            image_path=image_path,
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_inference_steps=i2v_steps,
            guidance_scale=i2v_guidance_scale,
            num_frames=num_frames,
            fps=fps,
            seed=seed
        )
        
        # Clean up intermediate files
        image_path.unlink(missing_ok=True)

        # Upload video to Cloudflare R2 and get presigned URL
        video_url: Optional[str] = None
        r2_key: Optional[str] = None

        r2_enabled = all([
            os.getenv("R2_ACCESS_KEY_ID"),
            os.getenv("R2_SECRET_ACCESS_KEY"),
            os.getenv("R2_BUCKET"),
            os.getenv("R2_ENDPOINT"),
        ])

        if r2_enabled:
            try:
                logger.info("📤 Uploading video to Cloudflare R2...")
                r2 = R2Client()
                r2_key = f"outputs/{job_id}/{video_path.name}"
                r2.upload_file(video_path, r2_key)
                # Presigned URL действителен 24 часа
                video_url = r2.get_presigned_url(r2_key, expires_in=86400)
                video_path.unlink(missing_ok=True)
                logger.info(f"✅ Video uploaded to R2: {r2_key}")
            except Exception as e:
                logger.warning(f"⚠️ R2 upload failed, returning local path: {e}")
        else:
            logger.warning("⚠️ R2 not configured (R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET/R2_ENDPOINT missing) — video_url will be null")

        # Return success result
        result = {
            "status": "success",
            "job_id": job_id,
            "video_url": video_url,        # presigned R2 URL (24h), null если R2 не настроен
            "video_path": str(video_path), # локальный путь (доступен только если R2 не настроен)
            "r2_key": r2_key,              # ключ в R2 для постоянного хранения
            "prompt": prompt,
            "parameters": {
                "t2i_steps": t2i_steps,
                "t2i_guidance_scale": t2i_guidance_scale,
                "i2v_steps": i2v_steps,
                "i2v_guidance_scale": i2v_guidance_scale,
                "num_frames": num_frames,
                "fps": fps,
                "seed": seed
            }
        }
        
        logger.info(f"✅ Job {job_id} completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"❌ Job {job_id} failed: {e}", exc_info=True)
        
        # Return error result
        return {
            "status": "error",
            "job_id": job_id,
            "error": str(e),
            "prompt": job_input.get("prompt", "")
        }


def main():
    """Main entry point for RunPod Serverless handler."""
    logger.info("=" * 60)
    logger.info("RunPod Serverless Video Generation Handler")
    logger.info("=" * 60)
    logger.info(f"T2I Model Path: {T2I_MODEL_PATH}")
    logger.info(f"I2V Model Path: {I2V_MODEL_PATH}")
    logger.info(f"HF_HUB_OFFLINE: {os.getenv('HF_HUB_OFFLINE', 'NOT SET')}")
    logger.info(f"PyTorch CUDA: {torch.cuda.is_available()}")
    logger.info("=" * 60)
    
    # Verify model paths exist
    if not os.path.exists(T2I_MODEL_PATH):
        logger.error(f"❌ T2I model not found at {T2I_MODEL_PATH}")
        logger.error("Please run scripts/prepare_runpod_volume.py to download models")
        sys.exit(1)
    
    if not os.path.exists(I2V_MODEL_PATH):
        logger.error(f"❌ I2V model not found at {I2V_MODEL_PATH}")
        logger.error("Please run scripts/prepare_runpod_volume.py to download models")
        sys.exit(1)
    
    # Start RunPod serverless handler
    runpod.serverless.start({"handler": process_job})


if __name__ == "__main__":
    main()