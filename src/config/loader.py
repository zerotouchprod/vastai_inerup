from typing import Optional
from .schema import PipelineConfig


def load_config(path: Optional[str] = None) -> PipelineConfig:
    """Load configuration from a local path or default location.
    For scaffold, return a minimal default config object."""
    # minimal placeholder implementation
    cfg = PipelineConfig()
    if path:
        cfg.source = path
    return cfg

