"""
Unit tests for generation configuration.
"""

import pytest
from pathlib import Path
from src.services.generation.config import GenerationConfig


def test_config_defaults():
    """Test default configuration values."""
    config = GenerationConfig()

    assert config.T2V_MODEL_ID == "THUDM/CogVideoX-5b"
    assert config.I2V_MODEL_ID == "THUDM/CogVideoX-5b-I2V"
    assert config.ENABLE_SAFETY_CHECKER is True
    assert config.DEFAULT_GUIDANCE_SCALE == 6.0
    assert config.DEFAULT_NUM_INFERENCE_STEPS == 50
    assert config.DEFAULT_NUM_FRAMES == 49
    assert config.USE_BFLOAT16 is True


def test_config_paths():
    """Test path properties."""
    config = GenerationConfig()

    temp_path = config.temp_dir_path
    assert isinstance(temp_path, Path)
    assert temp_path.exists()

    cache_path = config.hf_cache_path
    assert isinstance(cache_path, Path)


def test_config_optimization_kwargs():
    """Test optimization kwargs generation."""
    config = GenerationConfig()

    kwargs = config.get_optimization_kwargs()
    assert "cache_dir" in kwargs
    assert isinstance(kwargs["cache_dir"], str)


def test_config_validation():
    """Test parameter validation."""
    config = GenerationConfig()

    # Valid parameters
    config.validate_generation_params(
        guidance_scale=6.0,
        num_inference_steps=50,
        num_frames=49
    )

    # Invalid guidance_scale
    with pytest.raises(ValueError, match="guidance_scale"):
        config.validate_generation_params(
            guidance_scale=25.0,
            num_inference_steps=50,
            num_frames=49
        )

    # Invalid num_inference_steps
    with pytest.raises(ValueError, match="num_inference_steps"):
        config.validate_generation_params(
            guidance_scale=6.0,
            num_inference_steps=5,
            num_frames=49
        )

    # Invalid num_frames
    with pytest.raises(ValueError, match="num_frames"):
        config.validate_generation_params(
            guidance_scale=6.0,
            num_inference_steps=50,
            num_frames=150
        )


def test_config_from_env(monkeypatch):
    """Test loading configuration from environment variables."""
    monkeypatch.setenv("GEN_T2V_MODEL_ID", "custom/model")
    monkeypatch.setenv("GEN_DEFAULT_GUIDANCE_SCALE", "7.5")
    monkeypatch.setenv("GEN_ENABLE_SAFETY_CHECKER", "false")

    config = GenerationConfig()

    assert config.T2V_MODEL_ID == "custom/model"
    assert config.DEFAULT_GUIDANCE_SCALE == 7.5
    assert config.ENABLE_SAFETY_CHECKER is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
