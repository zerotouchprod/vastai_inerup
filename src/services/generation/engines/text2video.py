"""
CogVideoX Text-to-Video generation engine.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime

from .base import BaseVideoEngine
from src.services.generation.config import GenerationConfig
from src.domain.exceptions import ModelNotLoadedError, NSFWContentError


class CogVideoText2VideoEngine(BaseVideoEngine):
    """
    Engine for Text-to-Video generation using CogVideoX-5b.

    Features:
    - Generates videos from text prompts
    - Safety checking for NSFW content
    - Optimized for 24GB VRAM
    - Supports reproducible generation with seeds
    """

    def __init__(self, config: Optional[GenerationConfig] = None):
        """Initialize T2V engine."""
        super().__init__(config)
        self.model_id = self.config.T2V_MODEL_ID

    def initialize(self) -> None:
        """
        Load CogVideoX-5b model and apply optimizations.

        Raises:
            ImportError: If required libraries not available
            Exception: If model loading fails
        """
        if self._initialized:
            self.logger.info("Engine already initialized")
            return

        self.logger.info("=" * 60)
        self.logger.info(f"Loading Text-to-Video model: {self.model_id}")
        self.logger.info("=" * 60)

        try:
            from diffusers import CogVideoXPipeline
            import torch

            # Load pipeline
            self.logger.info("Loading pipeline...")
            start_time = datetime.now()

            self.pipe = CogVideoXPipeline.from_pretrained(
                self.model_id,
                **self.config.get_optimization_kwargs()
            )

            load_time = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"✓ Pipeline loaded in {load_time:.1f}s")

            # Apply optimizations
            self._apply_optimizations()

            # Load safety checker
            self._load_safety_checker()

            # Warmup (optional but recommended)
            if torch.cuda.is_available():
                self.logger.info("Performing warmup generation...")
                try:
                    _ = self.pipe(
                        prompt="warmup",
                        num_inference_steps=1,
                        num_frames=9
                    )
                    self.logger.info("✓ Warmup completed")
                except Exception as e:
                    self.logger.warning(f"Warmup failed (non-critical): {e}")

            self._initialized = True
            self.logger.info("=" * 60)
            self.logger.info("✅ Text-to-Video engine ready")
            self.logger.info("=" * 60)

        except ImportError as e:
            error_msg = f"Missing required library: {e}"
            self.logger.error(error_msg)
            raise ImportError(error_msg)

        except Exception as e:
            error_msg = f"Failed to initialize T2V engine: {e}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

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
            prompt: Text description of desired video
            negative_prompt: What to avoid in generation
            seed: Random seed for reproducibility
            guidance_scale: How closely to follow prompt (1.0-20.0)
            num_inference_steps: Quality vs speed tradeoff (10-200)
            num_frames: Video length (1-96)
            **kwargs: Additional pipeline parameters

        Returns:
            Path to generated video file

        Raises:
            ModelNotLoadedError: If engine not initialized
            NSFWContentError: If NSFW content detected
            Exception: If generation fails
        """
        if not self._initialized:
            raise ModelNotLoadedError("Engine not initialized. Call initialize() first.")

        # Use config defaults if not specified
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES

        # Validate parameters
        self.config.validate_generation_params(
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            num_frames=num_frames
        )

        self.logger.info("=" * 60)
        self.logger.info(f"Generating T2V: '{prompt[:60]}...'")
        self.logger.info(f"  Steps: {num_inference_steps}")
        self.logger.info(f"  Guidance: {guidance_scale}")
        self.logger.info(f"  Frames: {num_frames}")
        if seed is not None:
            self.logger.info(f"  Seed: {seed}")
        self.logger.info("=" * 60)

        start_time = datetime.now()

        try:
            import torch

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
            inference_time = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"✓ Generation completed in {inference_time:.1f}s")

            # Safety check
            if self.config.ENABLE_SAFETY_CHECKER:
                self.logger.info("Checking content safety...")
                if not self._check_safety(frames):
                    raise NSFWContentError("NSFW content detected in generated video")
                self.logger.info("✓ Content is safe")

            # Export to video file
            self.logger.info("Exporting video...")
            video_path = self._export_video(frames, prefix="t2v", fps=self.config.DEFAULT_FPS)

            total_time = (datetime.now() - start_time).total_seconds()
            self.logger.info("=" * 60)
            self.logger.info(f"✅ T2V generation successful")
            self.logger.info(f"  Output: {video_path}")
            self.logger.info(f"  Total time: {total_time:.1f}s")
            self.logger.info("=" * 60)

            return video_path

        except NSFWContentError:
            raise  # Re-raise NSFW errors

        except Exception as e:
            error_msg = f"T2V generation failed: {e}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
