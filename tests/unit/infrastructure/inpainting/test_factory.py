"""
Unit tests for inpainting factory functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.application.factories import ProcessorFactory
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.infrastructure.inpainting.sttn_adapter import STTNAdapter


class TestInpaintingFactory:
    """Unit tests for inpainting factory selection."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config.INPAINTING_ENGINE = "propainter"
        config.PROPAINTER_ROOT = Path("/opt/ProPainter")
        config.LAMA_MODEL_PATH = Path("/opt/lama_models/big-lama.pt")
        config.STTN_MODEL_PATH = Path("/opt/sttn_models/sttn.pth")
        return config
    
    @patch('src.core.config.get_config')
    def test_create_inpainter_propainter(self, mock_get_config, mock_config):
        """Test that factory creates ProPainterAdapter when config says so."""
        mock_config.INPAINTING_ENGINE = "propainter"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        with patch('src.application.factories.ProPainterAdapter') as mock_adapter:
            mock_adapter_instance = Mock()
            mock_adapter.return_value = mock_adapter_instance
            
            inpainter = factory._create_inpainter()
            
            # Verify ProPainterAdapter was created
            mock_adapter.assert_called_once()
            assert inpainter == mock_adapter_instance
    
    @patch('src.core.config.get_config')
    def test_create_inpainter_lama(self, mock_get_config, mock_config):
        """Test that factory creates LaMaAdapter when config says so."""
        mock_config.INPAINTING_ENGINE = "lama"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        with patch('src.application.factories.LaMaAdapter') as mock_adapter:
            mock_adapter_instance = Mock()
            mock_adapter.return_value = mock_adapter_instance
            
            inpainter = factory._create_inpainter()
            
            # Verify LaMaAdapter was created
            mock_adapter.assert_called_once()
            assert inpainter == mock_adapter_instance
    
    @patch('src.core.config.get_config')
    def test_create_inpainter_sttn(self, mock_get_config, mock_config):
        """Test that factory creates STTNAdapter when config says so."""
        mock_config.INPAINTING_ENGINE = "sttn"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        with patch('src.application.factories.STTNAdapter') as mock_adapter:
            mock_adapter_instance = Mock()
            mock_adapter.return_value = mock_adapter_instance
            
            inpainter = factory._create_inpainter()
            
            # Verify STTNAdapter was created
            mock_adapter.assert_called_once()
            assert inpainter == mock_adapter_instance
    
    @patch('src.core.config.get_config')
    def test_create_inpainter_fallback(self, mock_get_config, mock_config):
        """Test that factory falls back to ProPainter for unknown engine."""
        mock_config.INPAINTING_ENGINE = "unknown"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        with patch('src.application.factories.ProPainterAdapter') as mock_adapter:
            mock_adapter_instance = Mock()
            mock_adapter.return_value = mock_adapter_instance
            
            inpainter = factory._create_inpainter()
            
            # Verify ProPainterAdapter was created as fallback
            mock_adapter.assert_called_once()
            assert inpainter == mock_adapter_instance
    
    @patch('src.core.config.get_config')
    def test_create_subtitle_remover_with_lama(self, mock_get_config, mock_config):
        """Test that subtitle remover uses LaMa when configured."""
        mock_config.INPAINTING_ENGINE = "lama"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        # Mock all dependencies for SAM2 pipeline
        with patch('src.application.factories.PaddleWrapper') as mock_paddle, \
             patch('src.application.factories.Sam2Adapter') as mock_sam2, \
             patch('src.application.factories.TextMaskService') as mock_mask_service, \
             patch('src.application.factories.SubtitleRemoverService') as mock_service, \
             patch('src.application.factories.LaMaAdapter') as mock_lama_adapter, \
             patch('src.application.factories.ProcessorFactory._inject_pure_pytorch_corrblock'), \
             patch('src.application.factories.ProcessorFactory._patch_propainter_transformer'), \
             patch('src.application.factories.ProcessorFactory._inject_safe_matmul_into_transformer'), \
             patch('src.application.factories.ProcessorFactory._validate_corrblock_injection'), \
             patch('src.infrastructure.gpu.apply_global_stability_settings'), \
             patch('src.infrastructure.gpu.inject_stability_into_subprocess'), \
             patch('os.path.exists', return_value=True), \
             patch('os.getenv', return_value='0'):
            
            # Mock instances
            mock_paddle_instance = Mock()
            mock_paddle.return_value = mock_paddle_instance
            
            mock_sam2_instance = Mock()
            mock_sam2.return_value = mock_sam2_instance
            
            mock_mask_service_instance = Mock()
            mock_mask_service.return_value = mock_mask_service_instance
            
            mock_lama_instance = Mock()
            mock_lama_adapter.return_value = mock_lama_instance
            
            mock_service_instance = Mock()
            mock_service.return_value = mock_service_instance
            
            # Create subtitle remover
            result = factory.create_subtitle_remover(backend='sam2', lang='en')
            
            # Verify LaMaAdapter was created
            mock_lama_adapter.assert_called_once()
            
            # Verify SubtitleRemoverService was created with LaMa adapter
            mock_service.assert_called_once()
            call_args = mock_service.call_args
            assert call_args[0][1] == mock_lama_instance  # inpainter argument
    
    @patch('src.core.config.get_config')
    def test_create_subtitle_remover_with_sttn(self, mock_get_config, mock_config):
        """Test that subtitle remover uses STTN when configured."""
        mock_config.INPAINTING_ENGINE = "sttn"
        mock_get_config.return_value = mock_config
        
        factory = ProcessorFactory()
        
        # Mock all dependencies for SAM2 pipeline
        with patch('src.application.factories.PaddleWrapper') as mock_paddle, \
             patch('src.application.factories.Sam2Adapter') as mock_sam2, \
             patch('src.application.factories.TextMaskService') as mock_mask_service, \
             patch('src.application.factories.SubtitleRemoverService') as mock_service, \
             patch('src.application.factories.STTNAdapter') as mock_sttn_adapter, \
             patch('src.application.factories.ProcessorFactory._inject_pure_pytorch_corrblock'), \
             patch('src.application.factories.ProcessorFactory._patch_propainter_transformer'), \
             patch('src.application.factories.ProcessorFactory._inject_safe_matmul_into_transformer'), \
             patch('src.application.factories.ProcessorFactory._validate_corrblock_injection'), \
             patch('src.infrastructure.gpu.apply_global_stability_settings'), \
             patch('src.infrastructure.gpu.inject_stability_into_subprocess'), \
             patch('os.path.exists', return_value=True), \
             patch('os.getenv', return_value='0'):
            
            # Mock instances
            mock_paddle_instance = Mock()
            mock_paddle.return_value = mock_paddle_instance
            
            mock_sam2_instance = Mock()
            mock_sam2.return_value = mock_sam2_instance
            
            mock_mask_service_instance = Mock()
            mock_mask_service.return_value = mock_mask_service_instance
            
            mock_sttn_instance = Mock()
            mock_sttn_adapter.return_value = mock_sttn_instance
            
            mock_service_instance = Mock()
            mock_service.return_value = mock_service_instance
            
            # Create subtitle remover
            result = factory.create_subtitle_remover(backend='sam2', lang='en')
            
            # Verify STTNAdapter was created
            mock_sttn_adapter.assert_called_once()
            
            # Verify SubtitleRemoverService was created with STTN adapter
            mock_service.assert_called_once()
            call_args = mock_service.call_args
            assert call_args[0][1] == mock_sttn_instance  # inpainter argument
    
    def test_inpainting_engine_enum_values(self):
        """Test that INPAINTING_ENGINE enum has correct values."""
        # This test ensures the enum values match what the factory expects
        from src.core.config import InpaintingEngine
        
        assert InpaintingEngine.PROPAINTER.value == "propainter"
        assert InpaintingEngine.LAMA.value == "lama"
        assert InpaintingEngine.STTN.value == "sttn"
        
        # Test string conversion
        assert str(InpaintingEngine.PROPAINTER) == "InpaintingEngine.PROPAINTER"
        assert str(InpaintingEngine.LAMA) == "InpaintingEngine.LAMA"
        assert str(InpaintingEngine.STTN) == "InpaintingEngine.STTN"
        
        # Test value property
        assert InpaintingEngine.PROPAINTER.value == "propainter"
        assert InpaintingEngine.LAMA.value == "lama"
        assert InpaintingEngine.STTN.value == "sttn"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
