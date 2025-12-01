"""Test configuration loader."""

import pytest
import os
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from infrastructure.config import ConfigLoader, ProcessingConfig
from domain.exceptions import ConfigurationError


def test_config_loader_from_env():
    """Test loading config from environment variables."""
    os.environ['INPUT_URL'] = 'http://example.com/test.mp4'
    os.environ['MODE'] = 'upscale'
    os.environ['SCALE'] = '2.0'

    loader = ConfigLoader()
    config = loader.load()

    assert config.input_url == 'http://example.com/test.mp4'
    assert config.mode == 'upscale'
    assert config.scale == 2.0

    # Cleanup
    del os.environ['INPUT_URL']
    del os.environ['MODE']
    del os.environ['SCALE']


def test_config_validation_invalid_mode():
    """Test that invalid mode raises error."""
    with pytest.raises(ConfigurationError):
        ProcessingConfig(
            input_url='test.mp4',
            mode='invalid_mode'
        )


def test_config_validation_negative_scale():
    """Test that negative scale raises error."""
    with pytest.raises(ConfigurationError):
        ProcessingConfig(
            input_url='test.mp4',
            scale=-1.0
        )
