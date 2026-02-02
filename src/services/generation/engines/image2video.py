"""
CogVideoX Image-to-Video generation engine.
"""

from pathlib import Path
from typing import Optional
from datetime import datetime

from .base import BaseVideoEngine
from src.services.generation.config import GenerationConfig
from src.services.generation.utils.image_loader import ImageLoader
from src.domain.exceptions import ModelNotLoadedError, NSFWContentError


class CogVideoImage2VideoEngine(BaseVideoEngine):
    """
    Engine for Image-to-Video generation using CogVideoX-5b-I2V.

    Features:
    - Animates static images based on text prompts
    - Supports URL, base64, and local file inputs
    - Safety checking for NSFW content
    - Optimized for 24GB VRAM
    - Supports reproducible generation with seeds

    Best for:
    - Anime/stylized content animation
    - Adding motion to still images
    - Character animation from reference
    """

    def __init__(self, config: Optional[GenerationConfig] = None):
        """Initialize I2V engine."""
        super().__init__(config)
        self.model_id = self.config.I2V_MODEL_ID
        self.image_loader = ImageLoader()

    def initialize(self) -> None:
        """
        Load CogVideoX-5b-I2V model and apply optimizations.

        Raises:
            ImportError: If required libraries not available
            Exception: If model loading fails
        """
        if self._initialized:
            self.logger.info("Engine already initialized")
            return

        self.logger.info("=" * 60)
        self.logger.info(f"Loading Image-to-Video model: {self.model_id}")
        self.logger.info("=" * 60)

        try:
            from diffusers import CogVideoXImageToVideoPipeline
            import torch

            # Load pipeline
            self.logger.info("Loading I2V pipeline...")
            start_time = datetime.now()

            self.pipe = CogVideoXImageToVideoPipeline.from_pretrained(
                self.model_id,
                **self.config.get_optimization_kwargs()
            )

            load_time = (datetime.now() - start_time).total_seconds()
            self.logger.info(f"✓ Pipeline loaded in {load_time:.1f}s")

            # Apply optimizations
            self._apply_optimizations()

            # Load safety checker
            self._load_safety_checker()

            # Warmup (optional)
            if torch.cuda.is_available():
                self.logger.info("Performing warmup generation...")
                try:
                    from PIL import Image
                    # Create dummy image for warmup
                    dummy_image = Image.new('RGB', (512, 512), color='black')
                    _ = self.pipe(
                        prompt="warmup",
                        image=dummy_image,
                        num_inference_steps=1,
                        num_frames=9
                    )
                    self.logger.info("✓ Warmup completed")
                except Exception as e:
                    self.logger.warning(f"Warmup failed (non-critical): {e}")

            self._initialized = True
            self.logger.info("=" * 60)
            self.logger.info("✅ Image-to-Video engine ready")
            self.logger.info("=" * 60)

        except ImportError as e:
            error_msg = f"Missing required library: {e}"
            self.logger.error(error_msg)
            raise ImportError(error_msg)

        except Exception as e:
            error_msg = f"Failed to initialize I2V engine: {e}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

    def generate(
        self,
        prompt: str,
        input_image: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        **kwargs
    ) -> Path:
        """
        Generate video from image and text prompt.

        Args:
            prompt: Text description of desired animation/motion
            input_image: Image source (URL, base64 data URI, or file path)
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            guidance_scale: Guidance scale (default from config)
            num_inference_steps: Number of inference steps (default from config)
            num_frames: Number of frames to generate (default from config)
            **kwargs: Additional parameters (e.g., fps)

        Returns:
            Path to generated video file

        Raises:
            ModelNotLoadedError: If model not initialized
            NSFWContentError: If NSFW content detected
            ValueError: If image loading fails

        Example:
            engine = CogVideoImage2VideoEngine()
            engine.initialize()

            video_path = engine.generate(
                prompt="Make the character wave and smile",
                input_image="https://example.com/anime_character.jpg",
                seed=42,
                num_frames=49
            )
        """
        if not self._initialized:
            raise ModelNotLoadedError("Engine not initialized. Call initialize() first.")

        # Use config defaults if not provided
        guidance_scale = guidance_scale or self.config.DEFAULT_GUIDANCE_SCALE
        num_inference_steps = num_inference_steps or self.config.DEFAULT_NUM_INFERENCE_STEPS
        num_frames = num_frames or self.config.DEFAULT_NUM_FRAMES

        # Validate parameters
        self.config.validate_generation_params(
            guidance_scale=guidance_scale,
            num_inference_steps=num_inference_steps,
            num_frames=num_frames
        )

        # Load input image
        self.logger.info(f"Loading input image from: {input_image[:50]}...")
        try:
            image = self.image_loader.load(input_image)
            self.logger.info(f"✓ Input image loaded: {image.size} pixels")
        except Exception as e:
            raise ValueError(f"Failed to load input image: {e}")

        # Create generator with seed
        generator = self._create_generator(seed)

        # Log generation parameters
        self.logger.info("=" * 60)
        self.logger.info("Generating video from image...")
        self.logger.info(f"  Prompt: '{prompt[:60]}{'...' if len(prompt) > 60 else ''}'")
        self.logger.info(f"  Image: {image.size}")
        self.logger.info(f"  Steps: {num_inference_steps}")
        self.logger.info(f"  Frames: {num_frames}")
        self.logger.info(f"  Guidance: {guidance_scale}")
        if seed is not None:
            self.logger.info(f"  Seed: {seed}")
        self.logger.info("=" * 60)

        # Generate video
        start_time = datetime.now()

        try:
            output = self.pipe(
                prompt=prompt,
                image=image,
                negative_prompt=negative_prompt,
                num_inference_steps=num_inference_steps,
                num_frames=num_frames,
                guidance_scale=guidance_scale,
                generator=generator
            )
        except Exception as e:
            self.logger.error(f"Generation failed: {e}")
            raise RuntimeError(f"Video generation failed: {e}")

        generation_time = (datetime.now() - start_time).total_seconds()

        # Extract frames
        frames = output.frames[0]
        self.logger.info(f"✓ Generation completed in {generation_time:.1f}s ({len(frames)} frames)")

        # Safety check
        if not self._check_safety(frames):
            raise NSFWContentError("NSFW content detected in generated video")

        # Export to video file
        fps = kwargs.get('fps', self.config.DEFAULT_FPS)
        video_path = self._export_video(
            frames,
            prefix="i2v",
            fps=fps
        )

        file_size_mb = video_path.stat().st_size / (1024 * 1024)
        self.logger.info(f"✓ Video saved: {video_path.name} ({file_size_mb:.2f} MB)")

        return video_path
