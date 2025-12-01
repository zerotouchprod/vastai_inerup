"""
Unit tests for remote_config module.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

from shared.remote_config import (
    deep_merge,
    download_remote_config,
    load_config_with_remote,
    save_merged_config
)


class TestDeepMerge:
    """Test deep_merge function."""

    def test_simple_merge(self):
        """Test simple merge of two dicts."""
        base = {'a': 1, 'b': 2}
        override = {'b': 3, 'c': 4}
        
        result = deep_merge(base, override)
        
        assert result == {'a': 1, 'b': 3, 'c': 4}

    def test_nested_merge(self):
        """Test deep merge with nested dicts."""
        base = {
            'video': {'mode': 'upscale', 'scale': 2},
            'batch': {'input_dir': 'input/'}
        }
        override = {
            'video': {'scale': 4, 'target_fps': 60},
            'new_key': 'value'
        }
        
        result = deep_merge(base, override)
        
        assert result['video']['mode'] == 'upscale'  # preserved
        assert result['video']['scale'] == 4  # overridden
        assert result['video']['target_fps'] == 60  # added
        assert result['batch']['input_dir'] == 'input/'  # preserved
        assert result['new_key'] == 'value'  # added

    def test_override_non_dict_with_dict(self):
        """Test overriding non-dict value with dict."""
        base = {'video': 'simple'}
        override = {'video': {'mode': 'both'}}
        
        result = deep_merge(base, override)
        
        assert result['video'] == {'mode': 'both'}

    def test_empty_override(self):
        """Test merge with empty override."""
        base = {'a': 1, 'b': 2}
        override = {}
        
        result = deep_merge(base, override)
        
        assert result == {'a': 1, 'b': 2}


@patch('shared.remote_config.requests')
class TestDownloadRemoteConfig:
    """Test download_remote_config function."""

    def test_download_json_success(self, mock_requests):
        """Test successful JSON download."""
        mock_response = MagicMock()
        mock_response.json.return_value = {'video': {'mode': 'both'}}
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response
        
        result = download_remote_config('https://example.com/config.json')
        
        assert result == {'video': {'mode': 'both'}}
        mock_requests.get.assert_called_once_with('https://example.com/config.json', timeout=10)

    def test_download_yaml_fallback(self, mock_requests):
        """Test YAML parsing fallback when JSON fails."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.text = "video:\n  mode: both"
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response
        
        result = download_remote_config('https://example.com/config.yaml')
        
        assert result == {'video': {'mode': 'both'}}

    def test_download_network_error(self, mock_requests):
        """Test handling of network error."""
        mock_requests.get.side_effect = Exception("Network error")
        
        result = download_remote_config('https://example.com/config.json')
        
        assert result is None

    def test_download_invalid_content(self, mock_requests):
        """Test handling of non-dict response."""
        mock_response = MagicMock()
        mock_response.json.return_value = ["not", "a", "dict"]
        mock_response.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_response
        
        result = download_remote_config('https://example.com/config.json')
        
        assert result is None

    def test_download_empty_url(self, mock_requests):
        """Test handling of empty URL."""
        result = download_remote_config('')
        
        assert result is None
        mock_requests.get.assert_not_called()


class TestLoadConfigWithRemote:
    """Test load_config_with_remote function."""

    def test_load_config_no_remote_url(self, tmp_path):
        """Test loading config without remote URL."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("video:\n  mode: upscale\n")
        
        result = load_config_with_remote(config_file)
        
        assert result == {'video': {'mode': 'upscale'}}

    def test_load_config_file_not_found(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            load_config_with_remote(Path("/nonexistent/config.yaml"))

    @patch('shared.remote_config.download_remote_config')
    def test_load_config_with_remote_url(self, mock_download, tmp_path):
        """Test loading config with remote URL."""
        # Create local config
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "config_url: https://example.com/config.json\n"
            "video:\n  mode: upscale\n"
        )
        
        # Mock remote config
        mock_download.return_value = {
            'video': {'scale': 4, 'target_fps': 60}
        }
        
        result = load_config_with_remote(config_file)
        
        # Should merge local and remote
        assert result['video']['mode'] == 'upscale'  # from local
        assert result['video']['scale'] == 4  # from remote
        assert result['video']['target_fps'] == 60  # from remote

    @patch('shared.remote_config.download_remote_config')
    def test_load_config_remote_download_fails(self, mock_download, tmp_path):
        """Test fallback to local config when remote fails."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "config_url: https://example.com/config.json\n"
            "video:\n  mode: upscale\n"
        )
        
        mock_download.return_value = None  # Download failed
        
        result = load_config_with_remote(config_file)
        
        # Should use local config
        assert result == {
            'config_url': 'https://example.com/config.json',
            'video': {'mode': 'upscale'}
        }


class TestSaveMergedConfig:
    """Test save_merged_config function."""

    def test_save_config_success(self, tmp_path):
        """Test successful config save."""
        config_file = tmp_path / "config.yaml"
        config = {'video': {'mode': 'both', 'scale': 2}}
        
        result = save_merged_config(config, config_file)
        
        assert result is True
        assert config_file.exists()
        
        # Verify content
        import yaml
        with open(config_file) as f:
            loaded = yaml.safe_load(f)
        assert loaded == config

    def test_save_config_to_readonly_path(self):
        """Test error handling when saving to readonly path."""
        config = {'video': {'mode': 'both'}}
        
        result = save_merged_config(config, Path("/readonly/config.yaml"))
        
        assert result is False

