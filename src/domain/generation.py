"""
Domain layer for video generation.

Protocols, enums, and domain models following SOLID principles.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, Optional, List
from datetime import datetime


class GenerationMode(str, Enum):
    """Video generation modes."""
    TEXT2VIDEO = "text2video"
    IMAGE2VIDEO = "image2video"


class IVideoGenerator(Protocol):
    """Protocol for video generation engines."""

    def initialize(self) -> None:
        """Initialize the generation engine (load models)."""
        ...

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
            **kwargs: Additional parameters

        Returns:
            Path to generated video file

        Raises:
            GenerationError: If generation fails
            NSFWContentError: If NSFW content detected
        """
        ...

    def cleanup(self) -> None:
        """Clean up resources (free VRAM, etc.)."""
        ...


@dataclass
class VideoGenerationRequest:
    """Domain model for video generation request."""
    prompt: str
    mode: GenerationMode = GenerationMode.TEXT2VIDEO
    negative_prompt: Optional[str] = None
    input_image: Optional[str] = None  # URL or base64 for I2V
    seed: Optional[int] = None
    guidance_scale: float = 6.0
    num_inference_steps: int = 50
    num_frames: int = 49
    fps: int = 8


@dataclass
class GenerationMetadata:
    """Metadata about generated video."""
    job_id: str
    prompt: str
    mode: GenerationMode
    output_path: Path
    size_bytes: int
    duration_seconds: float
    num_frames: int
    fps: int
    generated_at: datetime
    inference_time_seconds: float
    seed_used: Optional[int] = None
