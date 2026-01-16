"""
Integration test to verify that configuration changes affect both ProPainterAdapter and SubtitleRemoverNative.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.core.config import get_config, AppConfig


class TestConfigIntegration:
    """Test that configuration is a single source of truth."""
    
    def test_config_values_propagate_to_propainter_adapter(self):
        """Test that MAX_HEIGHT config affects ProPainterAdapter resolution calculation."""
        from src.infrastructure.inpainting.components.resolution import ResolutionCalculator
        
        # Create a mock config with specific MAX_HEIGHT
        mock_config = Mock()
        mock_config.AUTO_DOWNSCALE = True
        mock_config.MAX_HEIGHT = 1080
        
        # Create ResolutionCalculator with mock config
        calculator = ResolutionCalculator(mock_config)
        
        # Test that MAX_HEIGHT is used in calculations
        # The actual calculation logic is tested in unit tests
        # Here we just verify that config is being used
        assert calculator.config == mock_config
        assert calculator.config.MAX_HEIGHT == 1080
        
        # Verify that calculate_target_dimensions uses MAX_HEIGHT
        with patch.object(calculator, '_should_downscale', return_value=True):
            width, height = calculator.calculate_target_dimensions(1920, 1080)
            # Should not downscale because height already equals MAX_HEIGHT
            assert height <= mock_config.MAX_HEIGHT
    
    def test_config_values_propagate_to_subtitle_remover_native(self):
        """Test that OCR_LANG config affects SubtitleRemoverNative initialization."""
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative
        
        # Mock dependencies
        with patch('src.infrastructure.processors.subtitle.native.PaddleOCR') as mock_paddleocr, \
             patch('src.infrastructure.utils.gpu_utils.require_gpu'), \
             patch('psutil.Process') as mock_process, \
             patch('src.core.config.get_config') as mock_get_config:
            
            # Setup mock config
            mock_config = Mock()
            mock_config.OCR_LANG = "ru"
            mock_config.MASK_DILATION = 15
            mock_config.CONFIDENCE_THRESHOLD = 0.1
            mock_config.USE_OPTICAL_FLOW = False
            mock_config.OPTICAL_FLOW_KEYFRAME_INTERVAL = 5
            mock_config.OPTICAL_FLOW_COLOR_THRESHOLD = 50.0
            mock_config.OPTICAL_FLOW_MOTION_THRESHOLD = 5.0
            mock_get_config.return_value = mock_config
            
            # Mock psutil
            mock_process_instance = Mock()
            mock_memory_info = Mock()
            mock_memory_info.rss = 1024 * 1024 * 100
            mock_process_instance.memory_info.return_value = mock_memory_info
            mock_process.return_value = mock_process_instance
            
            # Mock PaddleOCR
            mock_ocr_instance = Mock()
            mock_paddleocr.return_value = mock_ocr_instance
            
            # Create instance without arguments
            instance = SubtitleRemoverNative()
            
            # Verify config values are used
            assert instance.lang == "ru"
            assert instance.mask_dilation == 15
            assert instance.confidence_threshold == 0.1
            assert instance.use_optical_flow == False
    
    def test_config_priority_respected(self):
        """Test that argument priority (Argument -> Config -> Default) is respected."""
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative
        
        # Mock dependencies
        with patch('src.infrastructure.processors.subtitle.native.PaddleOCR') as mock_paddleocr, \
             patch('src.infrastructure.utils.gpu_utils.require_gpu'), \
             patch('psutil.Process') as mock_process, \
             patch('src.core.config.get_config') as mock_get_config:
            
            # Setup mock config with some values
            mock_config = Mock()
            mock_config.OCR_LANG = "ru"  # Config default
            mock_config.MASK_DILATION = 15
            mock_config.CONFIDENCE_THRESHOLD = 0.1
            mock_config.USE_OPTICAL_FLOW = False
            mock_config.OPTICAL_FLOW_KEYFRAME_INTERVAL = 5
            mock_config.OPTICAL_FLOW_COLOR_THRESHOLD = 50.0
            mock_config.OPTICAL_FLOW_MOTION_THRESHOLD = 5.0
            mock_get_config.return_value = mock_config
            
            # Mock psutil
            mock_process_instance = Mock()
            mock_memory_info = Mock()
            mock_memory_info.rss = 1024 * 1024 * 100
            mock_process_instance.memory_info.return_value = mock_memory_info
            mock_process.return_value = mock_process_instance
            
            # Mock PaddleOCR
            mock_ocr_instance = Mock()
            mock_paddleocr.return_value = mock_ocr_instance
            
            # Create instance with arguments that override config
            instance = SubtitleRemoverNative(
                lang="en",  # Override config
                mask_dilation=20,  # Override config
                # confidence_threshold not provided, should use config
                use_optical_flow=True  # Override config
            )
            
            # Verify argument values take priority
            assert instance.lang == "en"  # From argument, not config
            assert instance.mask_dilation == 20  # From argument, not config
            assert instance.confidence_threshold == 0.1  # From config (no argument)
            assert instance.use_optical_flow == True  # From argument, not config
    
    def test_real_config_instance(self):
        """Test with real AppConfig instance to ensure no import/initialization issues."""
        # Get real config instance
        config = get_config()
        
        # Verify it has expected attributes
        assert hasattr(config, 'PROPAINTER_ROOT')
        assert hasattr(config, 'MAX_FRAMES_PER_CHUNK')
        assert hasattr(config, 'PROPAINTER_OVERLAP')
        assert hasattr(config, 'AUTO_DOWNSCALE')
        assert hasattr(config, 'MAX_HEIGHT')
        assert hasattr(config, 'OCR_LANG')
        assert hasattr(config, 'MASK_DILATION')
        assert hasattr(config, 'CONFIDENCE_THRESHOLD')
        assert hasattr(config, 'USE_OPTICAL_FLOW')
        
        # Verify types
        assert isinstance(config.PROPAINTER_ROOT, Path)
        assert isinstance(config.MAX_FRAMES_PER_CHUNK, int)
        assert isinstance(config.PROPAINTER_OVERLAP, int)
        assert isinstance(config.AUTO_DOWNSCALE, bool)
        assert isinstance(config.MAX_HEIGHT, int)
        assert isinstance(config.OCR_LANG, str)
        assert isinstance(config.MASK_DILATION, int)
        assert isinstance(config.CONFIDENCE_THRESHOLD, float)
        assert isinstance(config.USE_OPTICAL_FLOW, bool)
