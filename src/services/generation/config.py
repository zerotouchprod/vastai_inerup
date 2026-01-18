"""
Configuration for text-to-video generation.
"""

from pydantic_settings import BaseSettings
from typing import Tuple, Optional
from pathlib import Path


class GenerationConfig(BaseSettings):
    """
    Configuration for video generation.
    
    Uses environment variables with prefix 'GEN_' for isolation.
    """
    
    # Model configuration
    MODEL_ID: str = "THUDM/CogVideoX-5b"
    ENABLE_SAFETY_CHECKER: bool = True
    SAFETY_CHECKER_MODEL: str = "CompVis/stable-diffusion-safety-checker"
    
    # Generation parameters
    DEFAULT_GUIDANCE_SCALE: float = 6.0
    DEFAULT_NUM_INFERENCE_STEPS: int = 50
    DEFAULT_NUM_FRAMES: int = 49  # ~6 seconds at 8fps
    DEFAULT_FPS: int = 8
    DEFAULT_SEED: Optional[int] = None
    
    # Video output
    OUTPUT_RESOLUTION: Tuple[int, int] = (720, 480)  # CogVideoX aspect ratio
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
    
    # Batch processing
    MAX_BATCH_SIZE: int = 4  # Maximum prompts to process in one job
    
    # Timeouts
    MODEL_LOAD_TIMEOUT: int = 300  # 5 minutes
    GENERATION_TIMEOUT: int = 600  # 10 minutes per video
    
    class Config:
        env_prefix = "GEN_"
        case_sensitive = False
        extra = "ignore"
    
    @property
    def torch_dtype(self):
        """Get torch dtype based on configuration."""
        # Lazy import to avoid requiring torch at module level
        import torch
        return torch.bfloat16 if self.USE_BFLOAT16 else torch.float32
    
    @property
    def temp_dir_path(self) -> Path:
        """Get temporary directory path."""
        path = Path(self.TEMP_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def hf_cache_path(self) -> Path:
        """Get HuggingFace cache path."""
        return Path(self.HF_CACHE_DIR)
    
    def get_optimization_kwargs(self) -> dict:
        """Get optimization kwargs for pipeline initialization."""
        return {
            "torch_dtype": self.torch_dtype,
            "cache_dir": str(self.hf_cache_path),
        }


def get_generation_config() -> GenerationConfig:
    """Get or create generation configuration instance."""
    return GenerationConfig()
