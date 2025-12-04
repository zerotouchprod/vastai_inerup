"""Configuration loading and validation."""

import os
import yaml
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from domain.exceptions import ConfigurationError
from shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ProcessingConfig:
    """Configuration for video processing."""

    # Input/Output
    input_url: str
    output_dir: Path = Path("/workspace/output")
    temp_dir: Path = Path("/tmp")

    # Processing mode
    mode: str = "both"  # 'upscale', 'interp', 'both'

    # Upscaling
    scale: float = 2.0
    target_resolution: Optional[str] = None

    # Interpolation
    interp_factor: float = 2.0
    target_fps: Optional[int] = None

    # Backend preferences
    prefer: str = "auto"  # 'auto', 'pytorch', 'ncnn', 'ffmpeg'
    strict: bool = False

    # Strategy for 'both' mode
    strategy: str = "interp-then-upscale"  # or 'upscale-then-interp'

    # Upload settings
    b2_bucket: Optional[str] = None
    b2_endpoint: Optional[str] = None
    b2_output_key: Optional[str] = None
    b2_key: Optional[str] = None
    b2_secret: Optional[str] = None

    # Processing options
    batch_args: Dict[str, Any] = field(default_factory=dict)
    smoke_seconds: int = 8
    smoke_timeout: int = 180

    # Misc
    keep_tmp: bool = False
    job_id: Optional[str] = None

    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate()

    def _validate(self):
        """Validate configuration values."""
        if self.mode not in ("upscale", "interp", "both"):
            raise ConfigurationError(f"Invalid mode: {self.mode}")

        if self.scale <= 0:
            raise ConfigurationError(f"Scale must be positive, got: {self.scale}")

        if self.interp_factor <= 0:
            raise ConfigurationError(f"Interp factor must be positive, got: {self.interp_factor}")

        if self.strategy not in ("interp-then-upscale", "upscale-then-interp"):
            raise ConfigurationError(f"Invalid strategy: {self.strategy}")

        if self.prefer not in ("auto", "pytorch", "ncnn", "ffmpeg"):
            raise ConfigurationError(f"Invalid prefer: {self.prefer}")


class ConfigLoader:
    """Loads and validates configuration from YAML files and environment variables."""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize config loader.

        Args:
            config_path: Optional path to YAML config file
        """
        self.config_path = config_path or Path("config.yaml")
        self._logger = get_logger(__name__)

    def load(self, overrides: Optional[Dict[str, Any]] = None) -> ProcessingConfig:
        """
        Load configuration from file and environment.

        Environment variables take precedence over config file.

        Returns:
            ProcessingConfig instance

        Raises:
            ConfigurationError: If configuration is invalid
        """
        config_dict = {}

        # Load from YAML if exists
        if self.config_path.exists():
            self._logger.info(f"Loading config from {self.config_path}")
            with open(self.config_path, 'r') as f:
                yaml_config = yaml.safe_load(f) or {}
                config_dict.update(yaml_config)
        else:
            self._logger.warning(f"Config file not found: {self.config_path}")

        # Override with environment variables
        env_config = self._load_from_env()
        config_dict.update(env_config)

        # Apply runtime overrides (from CLI) if provided
        if overrides:
            # Only accept known keys to avoid passing unexpected values
            for k, v in overrides.items():
                if v is None:
                    continue
                config_dict[k] = v

        # Validate required fields
        if "input_url" not in config_dict:
            raise ConfigurationError("input_url is required (set INPUT_URL or VIDEO_INPUT_URL)")

        # Filter to only known ProcessingConfig fields
        valid_fields = {
            'input_url', 'output_dir', 'temp_dir', 'mode', 'scale', 'target_resolution',
            'interp_factor', 'target_fps', 'prefer', 'strict', 'strategy',
            'b2_bucket', 'b2_endpoint', 'b2_output_key', 'b2_key', 'b2_secret',
            'batch_args', 'smoke_seconds', 'smoke_timeout', 'keep_tmp', 'job_id'
        }

        filtered_config = {k: v for k, v in config_dict.items() if k in valid_fields}

        try:
            return ProcessingConfig(**filtered_config)
        except TypeError as e:
            raise ConfigurationError(f"Invalid configuration: {e}")

    def _load_from_env(self) -> Dict[str, Any]:
        """Load configuration from environment variables."""
        env_config = {}

        # Input/Output
        if url := os.getenv("INPUT_URL") or os.getenv("VIDEO_INPUT_URL"):
            env_config["input_url"] = url

        if output_dir := os.getenv("OUTPUT_DIR"):
            env_config["output_dir"] = Path(output_dir)

        if temp_dir := os.getenv("TEMP_DIR") or os.getenv("TMP_DIR"):
            env_config["temp_dir"] = Path(temp_dir)

        # Processing mode
        if mode := os.getenv("MODE"):
            env_config["mode"] = mode.lower()

        # Upscaling
        if scale := os.getenv("SCALE"):
            try:
                env_config["scale"] = float(scale)
            except ValueError:
                self._logger.warning(f"Invalid SCALE value: {scale}")

        if target_res := os.getenv("TARGET_RESOLUTION") or os.getenv("TARGET_RES"):
            env_config["target_resolution"] = target_res

        # Interpolation
        if interp_factor := os.getenv("INTERP_FACTOR"):
            try:
                env_config["interp_factor"] = float(interp_factor)
            except ValueError:
                self._logger.warning(f"Invalid INTERP_FACTOR value: {interp_factor}")

        if target_fps := os.getenv("TARGET_FPS"):
            try:
                env_config["target_fps"] = int(target_fps)
            except ValueError:
                self._logger.warning(f"Invalid TARGET_FPS value: {target_fps}")

        # Backend
        if prefer := os.getenv("PREFER"):
            env_config["prefer"] = prefer.lower()

        if strict := os.getenv("STRICT"):
            env_config["strict"] = strict.lower() in ("true", "1", "yes")

        # Strategy
        if strategy := os.getenv("STRATEGY") or os.getenv("LOWRES_STRATEGY"):
            env_config["strategy"] = strategy

        # Upload settings
        if bucket := os.getenv("B2_BUCKET"):
            env_config["b2_bucket"] = bucket

        if endpoint := os.getenv("B2_ENDPOINT"):
            env_config["b2_endpoint"] = endpoint

        if output_key := os.getenv("B2_OUTPUT_KEY"):
            env_config["b2_output_key"] = output_key

        if b2_key := os.getenv("B2_KEY"):
            env_config["b2_key"] = b2_key

        if b2_secret := os.getenv("B2_SECRET"):
            env_config["b2_secret"] = b2_secret

        # Misc
        if keep_tmp := os.getenv("KEEP_TMP"):
            env_config["keep_tmp"] = keep_tmp.lower() in ("true", "1", "yes")

        if job_id := os.getenv("JOB_ID"):
            env_config["job_id"] = job_id

        return env_config
