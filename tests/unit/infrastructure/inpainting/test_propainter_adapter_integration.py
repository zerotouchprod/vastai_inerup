"""
Integration test for ProPainterAdapter with components.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.core.config import get_config
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter


class TestProPainterAdapterIntegration:
    """Integration tests for ProPainterAdapter with components."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config.PROPAINTER_ROOT = "/opt/ProPainter"
        config.MAX_FRAMES_PER_CHUNK = 15
        config.PROPAINTER_OVERLAP = 2
        config.AUTO_DOWNSCALE = True
        config.MAX_HEIGHT = 1080
        return config
    
    @patch('src.infrastructure.inpainting.propainter_adapter.get_config')
    @patch('src.infrastructure.inpainting.propainter_adapter.Path.exists')
    def test_adapter_initialization_with_components(self, mock_exists, mock_get_config, mock_config):
        """Test that ProPainterAdapter initializes with all components."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        # Mock component initialization
        with patch('src.infrastructure.inpainting.propainter_adapter.ResolutionCalculator') as mock_rc, \
             patch('src.infrastructure.inpainting.propainter_adapter.SlidingWindowStrategy') as mock_sws, \
             patch('src.infrastructure.inpainting.propainter_adapter.InferenceRunner') as mock_ir, \
             patch('src.infrastructure.inpainting.propainter_adapter.EnvironmentManager') as mock_em, \
             patch('src.infrastructure.inpainting.propainter_adapter.MediaProcessor') as mock_mp:
            
            # Mock EnvironmentManager.setup_gpu_environment to return proper dict
            mock_em_instance = Mock()
            mock_em_instance.setup_gpu_environment.return_value = {
                'num_gpus': 1,
                'devices': ['cuda:0'],
                'cuda_available': True,
                'gpus': [{'id': 0, 'name': 'Mock GPU', 'vram_gb': 8.0}],
                'total_vram_gb': 8.0
            }
            mock_em.return_value = mock_em_instance
            
            # Create adapter
            adapter = ProPainterAdapter()
            
            # Verify config was loaded
            mock_get_config.assert_called_once()
            assert adapter.config == mock_config
            
            # Verify components were initialized with config
            mock_rc.assert_called_once_with(mock_config)
            mock_sws.assert_called_once_with(mock_config)
            mock_ir.assert_called_once_with(mock_config, Path("/opt/ProPainter"))
            mock_em.assert_called_once_with(mock_config)
            mock_mp.assert_called_once_with(mock_config)
            
            # Verify component instances are stored
            assert adapter.resolution_calculator == mock_rc.return_value
            assert adapter.strategy == mock_sws.return_value
            assert adapter.inference_runner == mock_ir.return_value
            assert adapter.environment_manager == mock_em.return_value
            assert adapter.media_processor == mock_mp.return_value
            
            # Verify config values are used
            assert adapter.CHUNK_SIZE == mock_config.MAX_FRAMES_PER_CHUNK
            assert adapter.OVERLAP == mock_config.PROPAINTER_OVERLAP
    
    
    @patch('src.infrastructure.inpainting.propainter_adapter.get_config')
    @patch('src.infrastructure.inpainting.propainter_adapter.Path.exists')
    def test_adapter_config_priority(self, mock_exists, mock_get_config, mock_config):
        """Test that adapter respects config priority: Argument -> Config -> Default."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        # Test with argument overriding config
        custom_root = "/custom/ProPainter"
        
        # Mock EnvironmentManager
        mock_em = Mock()
        mock_em_instance = Mock()
        mock_em_instance.setup_gpu_environment.return_value = {
            'num_gpus': 1,
            'devices': ['cuda:0'],
            'cuda_available': True,
            'gpus': [{'id': 0, 'name': 'Mock GPU', 'vram_gb': 8.0}],
            'total_vram_gb': 8.0
        }
        mock_em.return_value = mock_em_instance
        
        with patch('src.infrastructure.inpainting.propainter_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.propainter_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.propainter_adapter.InferenceRunner'), \
             patch('src.infrastructure.inpainting.propainter_adapter.EnvironmentManager', new=mock_em), \
             patch('src.infrastructure.inpainting.propainter_adapter.MediaProcessor'):
            
            adapter = ProPainterAdapter(propainter_root=custom_root)
            
            # Verify argument takes priority over config
            assert str(adapter.root) == custom_root
            assert adapter.root != Path(mock_config.PROPAINTER_ROOT)
    
    def test_config_values_affect_behavior(self, mock_config):
        """Test that changing config values affects adapter behavior."""
        # Test different MAX_FRAMES_PER_CHUNK values
        test_cases = [
            (5, 5),   # Small chunk size
            (15, 15), # Default
            (30, 30), # Large chunk size
        ]
        
        for config_value, expected_value in test_cases:
            mock_config.MAX_FRAMES_PER_CHUNK = config_value
            
            # Mock EnvironmentManager
            mock_em = Mock()
            mock_em_instance = Mock()
            mock_em_instance.setup_gpu_environment.return_value = {
                'num_gpus': 1,
                'devices': ['cuda:0'],
                'cuda_available': True,
                'gpus': [{'id': 0, 'name': 'Mock GPU', 'vram_gb': 8.0}],
                'total_vram_gb': 8.0
            }
            mock_em.return_value = mock_em_instance
            
            with patch('src.infrastructure.inpainting.propainter_adapter.get_config', return_value=mock_config), \
                 patch('src.infrastructure.inpainting.propainter_adapter.Path.exists', return_value=True), \
                 patch('src.infrastructure.inpainting.propainter_adapter.ResolutionCalculator'), \
                 patch('src.infrastructure.inpainting.propainter_adapter.SlidingWindowStrategy'), \
                 patch('src.infrastructure.inpainting.propainter_adapter.InferenceRunner'), \
                 patch('src.infrastructure.inpainting.propainter_adapter.EnvironmentManager', new=mock_em), \
                 patch('src.infrastructure.inpainting.propainter_adapter.MediaProcessor'):
                
                adapter = ProPainterAdapter()
                assert adapter.CHUNK_SIZE == expected_value, \
                    f"Expected CHUNK_SIZE={expected_value} for MAX_FRAMES_PER_CHUNK={config_value}, got {adapter.CHUNK_SIZE}"
