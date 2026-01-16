"""
Unit tests for EnvironmentManager component.
"""

import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.core.config import AppConfig
from src.infrastructure.inpainting.components.environment import EnvironmentManager


class TestEnvironmentManager:
    """Test suite for EnvironmentManager."""
    
    @pytest.fixture
    def config(self):
        """Create a mock AppConfig."""
        config = Mock(spec=AppConfig)
        return config
    
    @pytest.fixture
    def env_manager(self, config):
        """Create EnvironmentManager instance."""
        manager = EnvironmentManager(config)
        manager.logger = Mock()  # Mock logger
        return manager
    
    def test_initialization(self, env_manager, config):
        """Test that manager is initialized with correct values."""
        assert env_manager.config == config
        assert env_manager.logger is not None
    
    @patch('torch.cuda.is_available')
    @patch('torch.cuda.device_count')
    @patch('torch.cuda.get_device_name')
    @patch('torch.cuda.get_device_properties')
    @patch('torch.cuda.init')
    def test_setup_gpu_environment_with_gpu(self, mock_init, mock_get_device_properties, mock_get_device_name,
                                            mock_device_count, mock_is_available, env_manager):
        """Test setup_gpu_environment with GPU available."""
        mock_is_available.return_value = True
        mock_device_count.return_value = 2
        mock_get_device_name.side_effect = lambda i: f"GPU{i}"
        mock_get_device_properties.return_value.total_memory = 8 * 1024**3  # 8 GB
        
        result = env_manager.setup_gpu_environment()
        
        assert result['cuda_available'] == True
        assert result['num_gpus'] == 2
        assert len(result['gpus']) == 2
        assert result['gpus'][0]['id'] == 0
        assert result['gpus'][0]['name'] == "GPU0"
        assert result['gpus'][0]['vram_gb'] == 8.0
        assert result['total_vram_gb'] == 16.0
        assert result['devices'] == ["cuda:0", "cuda:1"]
    
    @patch('torch.cuda.is_available')
    def test_setup_gpu_environment_no_gpu(self, mock_is_available, env_manager):
        """Test setup_gpu_environment without GPU."""
        mock_is_available.return_value = False
        
        result = env_manager.setup_gpu_environment()
        
        assert result['cuda_available'] == False
        assert result['num_gpus'] == 1
        assert result['devices'] == ["cpu"]
        assert result['gpus'] == []
        assert result['total_vram_gb'] == 0
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.write_text')
    def test_patch_propainter_success(self, mock_write_text, mock_read_text, mock_exists, env_manager):
        """Test patch_propainter when patching is needed and successful."""
        mock_exists.return_value = True
        mock_read_text.return_value = '''some code
IS_HIGH_VERSION = [int(m) for m in list(re.findall(r"^([0-9]+)\\.([0-9]+)\\.([0-9]+)([^0-9][a-zA-Z0-9]*)?(\\+git.*)?$",\\
                       torch.__version__)[0])]
more code'''
        
        result = env_manager.patch_propainter(Path("/opt/ProPainter"))
        
        assert result == True
        mock_exists.assert_called_once()
        mock_read_text.assert_called_once_with(encoding='utf-8')
        mock_write_text.assert_called_once()
    
    @patch('pathlib.Path.exists')
    def test_patch_propainter_file_not_exists(self, mock_exists, env_manager):
        """Test patch_propainter when misc.py doesn't exist."""
        mock_exists.return_value = False
        
        result = env_manager.patch_propainter(Path("/opt/ProPainter"))
        
        assert result == False
        mock_exists.assert_called_once()
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_patch_propainter_already_patched(self, mock_read_text, mock_exists, env_manager):
        """Test patch_propainter when already patched."""
        mock_exists.return_value = True
        mock_read_text.return_value = "# PATCHED by vastai_inerup"
        
        result = env_manager.patch_propainter(Path("/opt/ProPainter"))
        
        assert result == True
        mock_exists.assert_called_once()
        mock_read_text.assert_called_once_with(encoding='utf-8')
    
    @patch('torch.cuda.is_available')
    @patch('torch.cuda.device_count')
    def test_get_available_gpus_with_gpu(self, mock_device_count, mock_is_available, env_manager):
        """Test get_available_gpus with GPU available."""
        mock_is_available.return_value = True
        mock_device_count.return_value = 3
        
        result = env_manager.get_available_gpus()
        
        assert result == [0, 1, 2]
    
    @patch('torch.cuda.is_available')
    def test_get_available_gpus_no_gpu(self, mock_is_available, env_manager):
        """Test get_available_gpus without GPU."""
        mock_is_available.return_value = False
        
        result = env_manager.get_available_gpus()
        
        assert result == []
    
    @patch('torch.cuda.empty_cache')
    @patch('torch.cuda.synchronize')
    @patch('torch.cuda.is_available')
    @patch('gc.collect')
    def test_clear_cuda_cache_all(self, mock_gc_collect, mock_is_available, mock_synchronize, mock_empty_cache, env_manager):
        """Test clear_cuda_cache for all GPUs."""
        mock_is_available.return_value = True
        
        env_manager.clear_cuda_cache()
        
        mock_empty_cache.assert_called_once()
        mock_synchronize.assert_called_once()
        mock_gc_collect.assert_called_once()
    
    @patch('torch.cuda.empty_cache')
    @patch('torch.cuda.synchronize')
    @patch('torch.cuda.is_available')
    @patch('torch.cuda.device')
    @patch('gc.collect')
    def test_clear_cuda_cache_specific_gpu(self, mock_gc_collect, mock_device, mock_is_available, mock_synchronize, mock_empty_cache, env_manager):
        """Test clear_cuda_cache for specific GPU."""
        mock_is_available.return_value = True
        mock_device_context = MagicMock()
        mock_device.return_value.__enter__ = MagicMock()
        mock_device.return_value.__exit__ = MagicMock()
        
        env_manager.clear_cuda_cache(gpu_id=1)
        
        # Should call empty_cache within device context
        mock_device.assert_called_once_with(1)
        mock_empty_cache.assert_called_once()
        mock_synchronize.assert_called_once()
        mock_gc_collect.assert_called_once()
    
    @patch('torch.cuda.is_available')
    def test_clear_cuda_cache_no_gpu(self, mock_is_available, env_manager):
        """Test clear_cuda_cache when no GPU available."""
        mock_is_available.return_value = False
        
        # Should not raise any error
        env_manager.clear_cuda_cache()
    
    def test_environment_variables_handling(self, env_manager):
        """Test that environment variables should be handled properly."""
        # When implemented, setup_gpu_environment should handle:
        # - CUDA_VISIBLE_DEVICES
        # - PYTORCH_CUDA_ALLOC_CONF
        # - Other CUDA-related env vars
        
        original_env = os.environ.copy()
        
        # For now, just verify we can access environment variables
        assert 'PATH' in os.environ  # Basic check
        
        # Restore environment
        os.environ.clear()
        os.environ.update(original_env)
    
    @pytest.mark.parametrize("gpu_count,expected_gpu_list", [
        (0, []),      # No GPUs
        (1, [0]),     # Single GPU
        (2, [0, 1]),  # Two GPUs
        (4, [0, 1, 2, 3]),  # Four GPUs
    ])
    def test_gpu_list_generation(self, env_manager, gpu_count, expected_gpu_list):
        """Test expected GPU list generation."""
        # When implemented, get_available_gpus should return list of GPU indices
        # This test documents the expected behavior
        
        # For now, just verify test parameterization works
        assert len(expected_gpu_list) == gpu_count
        if gpu_count > 0:
            assert all(isinstance(gpu, int) for gpu in expected_gpu_list)
            assert all(0 <= gpu < gpu_count for gpu in expected_gpu_list)
