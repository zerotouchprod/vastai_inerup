"""
Configuration for video generation module (Text-to-Video & Image-to-Video).
"""

from pydantic_settings import BaseSettings
from typing import Tuple, Optional
from pathlib import Path


class GenerationConfig(BaseSettings):
    """
    Configuration for video generation.
    
    Uses environment variables with prefix 'GEN_' for isolation from main app.
    """
    
    # Model configuration
    T2V_MODEL_ID: str = "THUDM/CogVideoX-5b-I2V"  # Unified model for both T2V and I2V
    I2V_MODEL_ID: str = "THUDM/CogVideoX-5b-I2V"  # Same model, better for anime

    # Safety checker
    ENABLE_SAFETY_CHECKER: bool = True
    SAFETY_CHECKER_MODEL: str = "CompVis/stable-diffusion-safety-checker"
    SAFETY_CHECKER_THRESHOLD: float = 0.5

    # Generation parameters (defaults)
    DEFAULT_GUIDANCE_SCALE: float = 6.0
    DEFAULT_NUM_INFERENCE_STEPS: int = 50
    DEFAULT_NUM_FRAMES: int = 49  # ~6 seconds at 8fps
    DEFAULT_FPS: int = 8
    DEFAULT_SEED: Optional[int] = None
    
    # Video output
    OUTPUT_RESOLUTION: Tuple[int, int] = (720, 480)  # CogVideoX native resolution
    OUTPUT_CODEC: str = "libx264"
    OUTPUT_PIXEL_FORMAT: str = "yuv420p"
    
    # Paths
    HF_CACHE_DIR: str = "/root/.cache/huggingface"
    TEMP_DIR: str = "/tmp/generation"
    
    # Performance optimizations
    USE_BFLOAT16: bool = True
    ENABLE_CPU_OFFLOAD: bool = True
    ENABLE_VAE_SLICING: bool = True
    ENABLE_TILING: bool = True
    USE_XFORMERS: bool = True
    USE_TORCH_COMPILE: bool = False  # Experimental, slow warmup

    # Batch processing
    MAX_BATCH_SIZE: int = 100  # Maximum prompts per job
    ADAPTIVE_BATCH_SIZE: bool = False  # TODO: Phase 2

    # Timeouts (seconds)
    MODEL_LOAD_TIMEOUT: int = 300
    GENERATION_TIMEOUT: int = 600

    # Resource limits
    MAX_INFERENCE_STEPS: int = 200
    MAX_NUM_FRAMES: int = 96
    MAX_PROMPT_LENGTH: int = 1000

    class Config:
        env_prefix = "GEN_"
        case_sensitive = False
        extra = "ignore"
    
    @property
    def torch_dtype(self):
        """Get torch dtype based on configuration."""
        try:
            import torch
            return torch.bfloat16 if self.USE_BFLOAT16 else torch.float32
        except ImportError:
            return None

    @property
    def temp_dir_path(self) -> Path:
        """Get temporary directory path."""
        path = Path(self.TEMP_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def hf_cache_path(self) -> Path:
        """Get HuggingFace cache path."""
        path = Path(self.HF_CACHE_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_optimization_kwargs(self) -> dict:
        """
        Get optimization kwargs for pipeline initialization.

        Returns:
            Dict with torch_dtype and cache_dir
        """
        kwargs = {
            "cache_dir": str(self.hf_cache_path),
        }

        if self.torch_dtype is not None:
            kwargs["torch_dtype"] = self.torch_dtype

        return kwargs

    def validate_generation_params(
        self,
        guidance_scale: float,
        num_inference_steps: int,
        num_frames: int
    ) -> None:
        """
        Validate generation parameters.

        Args:
            guidance_scale: Guidance scale value
            num_inference_steps: Number of inference steps
            num_frames: Number of frames

        Raises:
            ValueError: If parameters are out of bounds
        """
        if not (1.0 <= guidance_scale <= 20.0):
            raise ValueError(f"guidance_scale must be 1.0-20.0, got {guidance_scale}")

        if not (10 <= num_inference_steps <= self.MAX_INFERENCE_STEPS):
            raise ValueError(
                f"num_inference_steps must be 10-{self.MAX_INFERENCE_STEPS}, "
                f"got {num_inference_steps}"
            )

        if not (1 <= num_frames <= self.MAX_NUM_FRAMES):
            raise ValueError(
                f"num_frames must be 1-{self.MAX_NUM_FRAMES}, "
                f"got {num_frames}"
            )


def get_generation_config() -> GenerationConfig:
    """Get or create generation configuration instance."""
    return GenerationConfig()
