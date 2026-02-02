"""
Unit tests for BaseVideoEngine.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path

from src.services.generation.engines.base import BaseVideoEngine
from src.services.generation.config import GenerationConfig
from src.domain.exceptions import ModelNotLoadedError


class TestEngine(BaseVideoEngine):
    """Concrete test implementation of BaseVideoEngine."""

    def initialize(self):
        self._initialized = True
        self.pipe = Mock()

    def generate(self, prompt, **kwargs):
        if not self._initialized:
            raise ModelNotLoadedError("Not initialized")
        return Path("/tmp/test.mp4")


def test_base_engine_initialization():
    """Test engine initialization."""
    config = GenerationConfig()
    engine = TestEngine(config)

    assert engine.config == config
    assert engine.pipe is None
    assert not engine._initialized


def test_base_engine_check_safety_no_checker():
    """Test safety check with no checker loaded."""
    engine = TestEngine()

    # Should return True (safe) when no checker
    result = engine._check_safety([Mock()])
    assert result is True


def test_base_engine_check_safety_empty_frames():
    """Test safety check with empty frames."""
    engine = TestEngine()
    engine.safety_checker = Mock()

    # Should return True for empty frames
    result = engine._check_safety([])
    assert result is True


@patch('src.services.generation.engines.base.torch')
def test_create_generator_with_seed(mock_torch):
    """Test generator creation with seed."""
    engine = TestEngine()
    mock_generator = Mock()
    mock_torch.Generator.return_value = mock_generator
    mock_torch.cuda.is_available.return_value = True

    result = engine._create_generator(seed=42)

    assert result == mock_generator
    mock_generator.manual_seed.assert_called_once_with(42)


@patch('src.services.generation.engines.base.torch')
def test_create_generator_without_seed(mock_torch):
    """Test generator creation without seed."""
    engine = TestEngine()

    result = engine._create_generator(seed=None)

    assert result is None
    mock_torch.Generator.assert_not_called()


def test_apply_optimizations():
    """Test optimization application."""
    engine = TestEngine()
    engine.pipe = Mock()
    engine.config.ENABLE_CPU_OFFLOAD = True
    engine.config.ENABLE_VAE_SLICING = True
    engine.config.ENABLE_TILING = True
    engine.config.USE_XFORMERS = False

    engine._apply_optimizations()

    engine.pipe.enable_model_cpu_offload.assert_called_once()
    engine.pipe.enable_vae_slicing.assert_called_once()
    engine.pipe.enable_tiling.assert_called_once()


def test_apply_optimizations_xformers():
    """Test xformers optimization."""
    engine = TestEngine()
    engine.pipe = Mock()
    engine.config.USE_XFORMERS = True

    engine._apply_optimizations()

    engine.pipe.enable_xformers_memory_efficient_attention.assert_called_once()


def test_apply_optimizations_xformers_not_available():
    """Test xformers when not available."""
    engine = TestEngine()
    engine.pipe = Mock()
    engine.pipe.enable_xformers_memory_efficient_attention.side_effect = ImportError("xformers not found")
    engine.config.USE_XFORMERS = True

    # Should not raise, just log warning
    engine._apply_optimizations()


@patch('src.services.generation.engines.base.torch')
def test_cleanup(mock_torch):
    """Test resource cleanup."""
    mock_torch.cuda.is_available.return_value = True

    engine = TestEngine()
    engine.initialize()
    engine.safety_checker = Mock()

    assert engine._initialized
    assert engine.pipe is not None

    engine.cleanup()

    assert engine.pipe is None
    assert engine.safety_checker is None
    assert not engine._initialized
    mock_torch.cuda.empty_cache.assert_called_once()


def test_context_manager():
    """Test engine as context manager."""
    engine = TestEngine()

    assert not engine._initialized

    with engine:
        assert engine._initialized

    # Should be cleaned up after context
    assert not engine._initialized


@patch('src.services.generation.engines.base.export_to_video')
def test_export_video(mock_export):
    """Test video export."""
    engine = TestEngine()
    frames = [Mock(), Mock(), Mock()]

    result = engine._export_video(frames, prefix="test", fps=24)

    assert isinstance(result, Path)
    assert result.name.startswith("test_")
    assert result.name.endswith(".mp4")
    mock_export.assert_called_once()


def test_load_safety_checker_disabled():
    """Test safety checker when disabled."""
    config = GenerationConfig()
    config.ENABLE_SAFETY_CHECKER = False

    engine = TestEngine(config)
    engine._load_safety_checker()

    assert engine.safety_checker is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
