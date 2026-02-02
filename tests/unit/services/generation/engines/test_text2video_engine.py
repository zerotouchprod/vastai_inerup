"""
Unit tests for CogVideoText2VideoEngine.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from src.services.generation.engines.text2video import CogVideoText2VideoEngine
from src.services.generation.config import GenerationConfig
from src.domain.exceptions import ModelNotLoadedError, NSFWContentError


@pytest.fixture
def config():
    """Create test configuration."""
    return GenerationConfig()


@pytest.fixture
def engine(config):
    """Create test engine."""
    return CogVideoText2VideoEngine(config)


def test_engine_initialization(engine, config):
    """Test engine initialization."""
    assert engine.config == config
    assert engine.model_id == config.T2V_MODEL_ID
    assert not engine._initialized
    assert engine.pipe is None


@patch('src.services.generation.engines.text2video.CogVideoXPipeline')
@patch('src.services.generation.engines.text2video.torch')
def test_initialize_success(mock_torch, mock_pipeline, engine):
    """Test successful engine initialization."""
    mock_torch.cuda.is_available.return_value = True
    mock_pipe = Mock()
    mock_pipeline.from_pretrained.return_value = mock_pipe

    engine.initialize()

    assert engine._initialized
    assert engine.pipe == mock_pipe
    mock_pipeline.from_pretrained.assert_called_once()


@patch('src.services.generation.engines.text2video.CogVideoXPipeline')
def test_initialize_already_initialized(mock_pipeline, engine):
    """Test initialization when already initialized."""
    engine._initialized = True

    engine.initialize()

    # Should not call from_pretrained again
    mock_pipeline.from_pretrained.assert_not_called()


@patch('src.services.generation.engines.text2video.CogVideoXPipeline')
def test_initialize_failure(mock_pipeline, engine):
    """Test initialization failure."""
    mock_pipeline.from_pretrained.side_effect = Exception("Model not found")

    with pytest.raises(Exception, match="Failed to initialize"):
        engine.initialize()


def test_generate_not_initialized(engine):
    """Test generate without initialization."""
    with pytest.raises(ModelNotLoadedError):
        engine.generate("test prompt")


@patch('src.services.generation.engines.text2video.torch')
def test_generate_success(mock_torch, engine):
    """Test successful video generation."""
    # Setup
    engine._initialized = True
    engine.pipe = Mock()

    # Mock output
    mock_frames = [Mock(), Mock(), Mock()]
    mock_output = Mock()
    mock_output.frames = [mock_frames]
    engine.pipe.return_value = mock_output

    # Mock export
    with patch.object(engine, '_export_video') as mock_export:
        mock_export.return_value = Path("/tmp/test.mp4")

        # Generate
        result = engine.generate("A test prompt")

        # Assertions
        assert isinstance(result, Path)
        engine.pipe.assert_called_once()
        mock_export.assert_called_once()


@patch('src.services.generation.engines.text2video.torch')
def test_generate_with_parameters(mock_torch, engine):
    """Test generation with custom parameters."""
    engine._initialized = True
    engine.pipe = Mock()

    mock_frames = [Mock()]
    mock_output = Mock()
    mock_output.frames = [mock_frames]
    engine.pipe.return_value = mock_output

    with patch.object(engine, '_export_video') as mock_export:
        mock_export.return_value = Path("/tmp/test.mp4")

        engine.generate(
            prompt="test",
            negative_prompt="bad quality",
            seed=42,
            guidance_scale=7.5,
            num_inference_steps=30,
            num_frames=25
        )

        # Check parameters passed to pipeline
        call_kwargs = engine.pipe.call_args[1]
        assert call_kwargs['prompt'] == "test"
        assert call_kwargs['negative_prompt'] == "bad quality"
        assert call_kwargs['guidance_scale'] == 7.5
        assert call_kwargs['num_inference_steps'] == 30
        assert call_kwargs['num_frames'] == 25


@patch('src.services.generation.engines.text2video.torch')
def test_generate_uses_config_defaults(mock_torch, engine):
    """Test that generation uses config defaults."""
    engine._initialized = True
    engine.pipe = Mock()

    mock_frames = [Mock()]
    mock_output = Mock()
    mock_output.frames = [mock_frames]
    engine.pipe.return_value = mock_output

    with patch.object(engine, '_export_video') as mock_export:
        mock_export.return_value = Path("/tmp/test.mp4")

        engine.generate("test")

        call_kwargs = engine.pipe.call_args[1]
        assert call_kwargs['guidance_scale'] == engine.config.DEFAULT_GUIDANCE_SCALE
        assert call_kwargs['num_inference_steps'] == engine.config.DEFAULT_NUM_INFERENCE_STEPS
        assert call_kwargs['num_frames'] == engine.config.DEFAULT_NUM_FRAMES


@patch('src.services.generation.engines.text2video.torch')
def test_generate_nsfw_detected(mock_torch, engine):
    """Test NSFW content detection."""
    engine._initialized = True
    engine.pipe = Mock()
    engine.config.ENABLE_SAFETY_CHECKER = True

    mock_frames = [Mock()]
    mock_output = Mock()
    mock_output.frames = [mock_frames]
    engine.pipe.return_value = mock_output

    # Mock safety check to return False
    with patch.object(engine, '_check_safety', return_value=False):
        with pytest.raises(NSFWContentError):
            engine.generate("test prompt")


def test_generate_invalid_parameters(engine):
    """Test generation with invalid parameters."""
    engine._initialized = True

    with pytest.raises(ValueError, match="guidance_scale"):
        engine.generate("test", guidance_scale=25.0)

    with pytest.raises(ValueError, match="num_inference_steps"):
        engine.generate("test", num_inference_steps=5)

    with pytest.raises(ValueError, match="num_frames"):
        engine.generate("test", num_frames=150)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
