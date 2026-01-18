"""
CogVideoX engine for text-to-video generation.
"""

import torch
import tempfile
import uuid
from pathlib import Path
from typing import Optional, List, Tuple, Any
from datetime import datetime

from diffusers import CogVideoXPipeline
from diffusers.utils import export_to_video
from transformers import pipeline as transformers_pipeline

from .config import GenerationConfig
from .models import GenerationResult
from src.shared.logging import get_logger


class CogVideoEngine:
    """
    Engine for text-to-video generation using CogVideoX-5b.
    
    Features:
    - Safety checking with Stable Diffusion safety checker
    - Optimizations for 24GB VRAM (CPU offload, VAE slicing, tiling)
    - Batch processing support
    - NSFW content filtering
    """
    
    def __init__(self, config: Optional[GenerationConfig] = None):
        """
        Initialize the generation engine.
        
        Args:
            config: Generation configuration (uses default if None)
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)
        
        self.pipe: Optional[CogVideoXPipeline] = None
        self.safety_checker = None
        self._initialized = False
        
    def initialize(self) -> None:
        """Initialize the pipeline and safety checker."""
        if self._initialized:
            return
            
        self.logger.info(f"Initializing CogVideoEngine with model: {self.config.MODEL_ID}")
        
        try:
            # Load pipeline with optimizations
            self.logger.info("Loading CogVideoX pipeline...")
            self.pipe = CogVideoXPipeline.from_pretrained(
                self.config.MODEL_ID,
                **self.config.get_optimization_kwargs()
            )
            
            # Apply optimizations
            if self.config.ENABLE_CPU_OFFLOAD:
                self.pipe.enable_model_cpu_offload()
                self.logger.info("Enabled model CPU offload")
            
            if self.config.ENABLE_VAE_SLICING:
                self.pipe.enable_vae_slicing()
                self.logger.info("Enabled VAE slicing")
            
            if self.config.ENABLE_TILING:
                self.pipe.enable_tiling()
                self.logger.info("Enabled tiling")
            
            if self.config.USE_XFORMERS:
                try:
                    self.pipe.enable_xformers_memory_efficient_attention()
                    self.logger.info("Enabled xformers memory efficient attention")
                except ImportError:
                    self.logger.warning("xformers not available, skipping")
            
            # Initialize safety checker if enabled
            if self.config.ENABLE_SAFETY_CHECKER:
                self.logger.info(f"Loading safety checker: {self.config.SAFETY_CHECKER_MODEL}")
                self.safety_checker = transformers_pipeline(
                    "image-classification",
                    model=self.config.SAFETY_CHECKER_MODEL,
                    device="cuda" if torch.cuda.is_available() else "cpu"
                )
            
            self._initialized = True
            self.logger.info("CogVideoEngine initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize CogVideoEngine: {e}")
            raise
    
    def _check_safety(self, frames: List) -> bool:
        """
        Check frames for NSFW content.
        
        Args:
            frames: List of frames to check
            
        Returns:
            True if content is safe, False if NSFW detected
        """
        if not self.safety_checker or not frames:
            return True
        
        try:
            # Check a sample of frames (first, middle, last)
            sample_indices = [0, len(frames) // 2, -1]
            sample_frames = [frames[i] for i in sample_indices if i < len(frames)]
            
            for frame in sample_frames:
                results = self.safety_checker(frame, top_k=2)
                
                # Check for NSFW classifications
                for result in results:
                    label = result['label'].lower()
                    score = result['score']
                    
                    if 'nsfw' in label or 'explicit' in label or 'adult' in label:
                        if score > 0.5:  # Confidence threshold
                            self.logger.warning(f"NSFW content detected: {label} (score: {score:.3f})")
                            return False
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Safety check failed: {e}, allowing content")
            return True  # Fail open for safety
    
    def _create_generator(self, seed: Optional[int] = None) -> Optional[torch.Generator]:
        """
        Create torch generator with optional seed.
        
        Args:
            seed: Random seed
            
        Returns:
            torch.Generator or None
        """
        if seed is not None:
            generator = torch.Generator(device="cuda")
            generator.manual_seed(seed)
            return generator
        return None
    
    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """
        Generate video from text prompt.
        
        Args:
            prompt: Text prompt for generation
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            guidance_scale: Guidance scale
            num_inference_steps: Number of inference steps
            num_frames: Number of frames to generate
            **kwargs: Additional pipeline parameters
            
        Returns:
            Path to generated video file
        """
        if not self._initialized:
            self.initialize()
        
        # Use config defaults if not specified
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        
        self.logger.info(
            f"Generating video: '{prompt[:50]}...' "
            f"(steps: {num_inference_steps}, guidance: {guidance_scale}, frames: {num_frames})"
        )
        
        start_time = datetime.now()
        
        try:
            # Generate frames
            with torch.inference_mode():
                output = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    num_videos_per_prompt=1,
                    num_inference_steps=num_inference_steps,
                    num_frames=num_frames,
                    guidance_scale=guidance_scale,
                    generator=self._create_generator(seed),
                    **kwargs
                )
            
            frames = output.frames[0]
            
            # Safety check
            if not self._check_safety(frames):
                raise ValueError("NSFW content detected in generated video")
            
            # Create temporary file
            temp_dir = self.config.temp_dir_path
            temp_dir.mkdir(parents=True, exist_ok=True)
            output_path = temp_dir / f"generated_{uuid.uuid4().hex[:8]}.mp4"
            
            # Export to video
            export_to_video(
                frames,
                str(output_path),
                fps=self.config.DEFAULT_FPS
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info(
                f"Video generated successfully: {output_path} "
                f"({output_path.stat().st_size / 1024 / 1024:.2f} MB, {duration:.1f}s)"
            )
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Video generation failed: {e}")
            raise
    
    def generate_batch(
        self,
        prompts: List[str],
        **kwargs
    ) -> List[Tuple[str, Path]]:
        """
        Generate videos for multiple prompts.
        
        Args:
            prompts: List of text prompts
            **kwargs: Generation parameters passed to generate()
            
        Returns:
            List of (prompt, output_path) tuples
        """
        if not self._initialized:
            self.initialize()
        
        results = []
        total = len(prompts)
        
        for i, prompt in enumerate(prompts, 1):
            self.logger.info(f"Processing prompt {i}/{total}: '{prompt[:50]}...'")
            
            try:
                output_path = self.generate(prompt, **kwargs)
                results.append((prompt, output_path))
                
            except Exception as e:
                self.logger.error(f"Failed to generate video for prompt {i}: {e}")
                # Continue with next prompt
                continue
        
        return results
    
    def cleanup(self) -> None:
        """Clean up resources."""
        if self.pipe:
            try:
                # Clear pipeline from GPU memory
                self.pipe = None
                torch.cuda.empty_cache()
                self.logger.info("Cleaned up pipeline resources")
            except Exception as e:
                self.logger.warning(f"Error during cleanup: {e}")
        
        self._initialized = False
    
    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
