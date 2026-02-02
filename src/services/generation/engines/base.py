"""
Base engine for video generation.
"""

import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from src.services.generation.config import GenerationConfig
from src.shared.logging import get_logger
from src.domain.exceptions import ModelNotLoadedError, NSFWContentError


class BaseVideoEngine(ABC):
    """
    Abstract base class for video generation engines.

    Implements common functionality like safety checking, generator creation,
    and resource cleanup. Subclasses implement mode-specific generation logic.
    """

    def __init__(self, config: Optional[GenerationConfig] = None):
        """
        Initialize the engine.

        Args:
            config: Generation configuration (uses default if None)
        """
        self.config = config or GenerationConfig()
        self.logger = get_logger(__name__)

        self.pipe = None
        self.safety_checker = None
        self._initialized = False

    @abstractmethod
    def initialize(self) -> None:
        """
        Initialize the generation pipeline (load models).

        Must be implemented by subclasses to load specific models.
        """
        pass

    @abstractmethod
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
        Generate video from prompt.

        Args:
            prompt: Text prompt for generation
            negative_prompt: Negative prompt for guidance
            seed: Random seed for reproducibility
            guidance_scale: Guidance scale
            num_inference_steps: Number of inference steps
            num_frames: Number of frames to generate
            **kwargs: Additional mode-specific parameters

        Returns:
            Path to generated video file

        Raises:
            ModelNotLoadedError: If model not initialized
            NSFWContentError: If NSFW content detected
        """
        pass

    def _check_safety(self, frames: List) -> bool:
        """
        Check frames for NSFW content using safety checker.

        Args:
            frames: List of frames to check

        Returns:
            True if content is safe, False if NSFW detected
        """
        if not self.safety_checker or not frames:
            return True

        try:
            # Check middle frame only (optimized)
            middle_idx = len(frames) // 2
            sample_frame = frames[middle_idx]

            results = self.safety_checker(sample_frame, top_k=2)

            # Check for NSFW classifications
            for result in results:
                label = result['label'].lower()
                score = result['score']

                if any(keyword in label for keyword in ['nsfw', 'explicit', 'adult']):
                    if score > self.config.SAFETY_CHECKER_THRESHOLD:
                        self.logger.warning(
                            f"NSFW content detected: {label} (score: {score:.3f})"
                        )
                        return False

            return True

        except Exception as e:
            self.logger.warning(f"Safety check failed: {e}, allowing content")
            return True  # Fail open for safety check errors

    def _create_generator(self, seed: Optional[int] = None):
        """
        Create torch generator with optional seed.

        Args:
            seed: Random seed

        Returns:
            torch.Generator or None
        """
        if seed is not None:
            try:
                import torch
                generator = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu")
                generator.manual_seed(seed)
                return generator
            except ImportError:
                self.logger.warning("torch not available, seed will be ignored")
                return None
        return None

    def _export_video(
        self,
        frames: List,
        prefix: str = "video",
        fps: Optional[int] = None
    ) -> Path:
        """
        Export frames to video file.

        Args:
            frames: List of frames
            prefix: Filename prefix
            fps: Frames per second (uses config default if None)

        Returns:
            Path to exported video file
        """
        try:
            from diffusers.utils import export_to_video
        except ImportError:
            raise ImportError("diffusers library required for video export")

        fps = fps or self.config.DEFAULT_FPS

        # Create unique filename
        temp_dir = self.config.temp_dir_path
        output_path = temp_dir / f"{prefix}_{uuid.uuid4().hex[:8]}.mp4"

        # Export
        export_to_video(
            frames,
            str(output_path),
            fps=fps
        )

        file_size_mb = output_path.stat().st_size / 1024 / 1024
        self.logger.info(f"Video exported: {output_path.name} ({file_size_mb:.2f} MB)")

        return output_path

    def _apply_optimizations(self) -> None:
        """Apply performance optimizations to pipeline."""
        if not self.pipe:
            return

        if self.config.ENABLE_CPU_OFFLOAD:
            self.pipe.enable_model_cpu_offload()
            self.logger.info("✓ Enabled CPU offload")

        if self.config.ENABLE_VAE_SLICING:
            self.pipe.enable_vae_slicing()
            self.logger.info("✓ Enabled VAE slicing")

        if self.config.ENABLE_TILING:
            self.pipe.enable_tiling()
            self.logger.info("✓ Enabled tiling")

        if self.config.USE_XFORMERS:
            try:
                self.pipe.enable_xformers_memory_efficient_attention()
                self.logger.info("✓ Enabled xformers memory efficient attention")
            except (ImportError, AttributeError) as e:
                self.logger.warning(f"xformers not available: {e}")

    def _load_safety_checker(self) -> None:
        """Load safety checker model."""
        if not self.config.ENABLE_SAFETY_CHECKER:
            return

        try:
            from transformers import pipeline as transformers_pipeline
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.safety_checker = transformers_pipeline(
                "image-classification",
                model=self.config.SAFETY_CHECKER_MODEL,
                device=device
            )
            self.logger.info(f"✓ Safety checker loaded on {device}")

        except Exception as e:
            self.logger.warning(f"Failed to load safety checker: {e}")
            self.safety_checker = None

    def cleanup(self) -> None:
        """Clean up resources and free VRAM."""
        if self.pipe is not None:
            del self.pipe
            self.pipe = None

        if self.safety_checker is not None:
            del self.safety_checker
            self.safety_checker = None

        # Force garbage collection
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                self.logger.info("✓ VRAM cleared")
        except ImportError:
            pass

        self._initialized = False
        self.logger.info("Engine cleaned up")

    def __enter__(self):
        """Context manager entry."""
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
        return False
