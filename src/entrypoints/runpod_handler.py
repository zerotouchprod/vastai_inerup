#!/usr/bin/env python3
"""
RunPod Serverless Handler for Video Generation

This handler processes video generation jobs in a serverless environment.
Models are loaded from a mounted network volume at /runpod-volume/models/
"""

import os
import sys
import json
import tempfile
import uuid
import gc
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
from src.services.storage.b2_client import B2Client

# Configure logging
logger = get_logger(__name__)

# Model paths (mounted from RunPod Network Volume)
T2I_MODEL_PATH = "/runpod-volume/models/dreamshaper-xl-lightning"
I2V_MODEL_PATH = "/runpod-volume/models/CogVideoX-5b-I2V"

# Default generation parameters
DEFAULT_T2I_STEPS = 4
DEFAULT_T2I_GUIDANCE_SCALE = 0.0
DEFAULT_I2V_STEPS = 25
DEFAULT_I2V_GUIDANCE_SCALE = 6.0
DEFAULT_NUM_FRAMES = 16
DEFAULT_FPS = 8

# Initialize B2 client (if credentials available)
b2_client = None
try:
    # Try to initialize B2 client from environment variables
    b2_client = B2Client()
    logger.info("B2 client initialized successfully")
except Exception as e:
    logger.warning(f"B2 client initialization failed: {e}. Videos will be stored locally.")


def load_t2i_pipeline() -> StableDiffusionXLPipeline:
    """
    Load Text-to-Image pipeline from local model path.
    
    Returns:
        StableDiffusionXLPipeline instance
    """
    logger.info(f"Loading T2I model from: {T2I_MODEL_PATH}")
    
    if not os.path.exists(T2I_MODEL_PATH):
        raise FileNotFoundError(f"T2I model not found at {T2I_MODEL_PATH}")
    
    # Load pipeline with optimizations
    pipeline = StableDiffusionXLPipeline.from_pretrained(
        T2I_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
        use_safetensors=True
    )
    
    # Move to GPU and apply optimizations
    pipeline = pipeline.to("cuda")
    
    # Apply optimizations for 24GB VRAM
    if hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()
    
    if hasattr(pipeline, "enable_vae_tiling"):
        pipeline.enable_vae_tiling()
    
    logger.info("✓ T2I pipeline loaded")
    return pipeline


def load_i2v_pipeline() -> CogVideoXImageToVideoPipeline:
    """
    Load Image-to-Video pipeline from local model path.
    
    Returns:
        CogVideoXImageToVideoPipeline instance
    """
    logger.info(f"Loading I2V model from: {I2V_MODEL_PATH}")
    
    if not os.path.exists(I2V_MODEL_PATH):
        raise FileNotFoundError(f"I2V model not found at {I2V_MODEL_PATH}")
    
    # Load pipeline with optimizations
    pipeline = CogVideoXImageToVideoPipeline.from_pretrained(
        I2V_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
        use_safetensors=True
    )
    
    # Move to GPU and apply optimizations
    pipeline = pipeline.to("cuda")
    
    # Apply optimizations
    if hasattr(pipeline, "enable_model_cpu_offload"):
        pipeline.enable_model_cpu_offload()
    
    if hasattr(pipeline, "enable_vae_slicing"):
        pipeline.enable_vae_slicing()
    
    logger.info("✓ I2V pipeline loaded")
    return pipeline


def cleanup_vram():
    """
    Aggressively clean up VRAM by deleting pipelines and forcing garbage collection.
    """
    logger.info("Cleaning up VRAM...")
    
    # Force garbage collection
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
        
        # Generate image
        with torch.inference_mode():
            image = t2i_pipeline(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=generator,
            ).images[0]
        
        # Save image to temporary file
        temp_dir = Path("/tmp/generation")
        temp_dir.mkdir(parents=True, exist_ok=True)
        image_path = temp_dir / f"ref_image_{uuid.uuid4().hex[:8]}.png"
        image.save(image_path)
        
        logger.info(f"✓ Image generated: {image_path}")
        return image_path
        
    finally:
        # Clean up T2I pipeline
        del t2i_pipeline
        cleanup_vram()


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
        # Load reference image
        image = Image.open(image_path)
        
        # Create generator with seed if provided
        generator = None
        if seed is not None:
            generator = torch.Generator(device="cuda").manual_seed(seed)
        
        # Generate video frames
        with torch.inference_mode():
            # Remove fps from kwargs as CogVideoX doesn't support it
            output = i2v_pipeline(
                image=image,
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                num_frames=num_frames,
                generator=generator,
            )
        
        frames = output.frames[0]
        
        # Save video to temporary file
        temp_dir = Path("/tmp/generation")
        temp_dir.mkdir(parents=True, exist_ok=True)
        video_path = temp_dir / f"video_{uuid.uuid4().hex[:8]}.mp4"
        
        # Export frames to video
        export_to_video(
            frames,
            str(video_path),
            fps=fps
        )
        
        logger.info(f"✓ Video generated: {video_path} ({video_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return video_path
        
    finally:
        # Clean up I2V pipeline
        del i2v_pipeline
        cleanup_vram()


def upload_to_storage(video_path: Path, job_id: str) -> str:
    """
    Upload video to cloud storage (B2/Cloudflare R2/S3).
    
    Args:
        video_path: Path to video file
        job_id: Job ID for naming
        
    Returns:
        URL of uploaded video
    """
    if b2_client is None:
        # Return local file URL if B2 client not available
        return f"file://{video_path}"
    
    try:
        # Generate unique output key
        output_key = f"runpod/generated/{job_id}_{video_path.name}"
        
        # Upload to B2
        logger.info(f"Uploading to B2: {output_key}")
        b2_client.upload_file(video_path, output_key)
        
        # Get presigned URL
        url = b2_client.get_presigned_url(output_key)
        logger.info(f"✓ Upload complete: {url}")
        
        # Delete local file after successful upload
        video_path.unlink(missing_ok=True)
        
        return url
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        # Fall back to local file
        return f"file://{video_path}"


def process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main job processing function for RunPod Serverless.
    
    Args:
        job: Job dictionary from RunPod
        
    Returns:
        Result dictionary with status and video URL
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
        num_frames = job_input.get("num_frames", DEFAULT_NUM_FRAMES)
        fps = job_input.get("fps", DEFAULT_FPS)
        
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
        
        # Clean up image file
        image_path.unlink(missing_ok=True)
        
        # Phase 3: Upload to storage
        logger.info("=" * 60)
        logger.info("PHASE 3: Upload to Cloud Storage")
        logger.info("=" * 60)
        
        video_url = upload_to_storage(video_path, job_id)
        
        # Return success result
        result = {
            "status": "success",
            "job_id": job_id,
            "video_url": video_url,
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
    logger.info(f"B2 Client: {'Available' if b2_client else 'Not available'}")
    logger.info("=" * 60)
    
    # Start RunPod serverless handler
    runpod.serverless.start({"handler": process_job})


if __name__ == "__main__":
    main()