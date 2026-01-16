"""
Test that SubtitleRemoverNative uses configuration from AppConfig.
"""

import sys
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Mock cv2 before importing SubtitleRemoverNative
sys.modules['cv2'] = Mock()
sys.modules['numpy'] = Mock()
sys.modules['psutil'] = Mock()

from src.core.config import get_config
from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative


class TestSubtitleRemoverNativeConfig:
    """Test configuration usage in SubtitleRemoverNative."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config.OCR_LANG = "ru"
        config.MASK_DILATION = 15
        config.CONFIDENCE_THRESHOLD = 0.1
        config.USE_OPTICAL_FLOW = False
        config.OPTICAL_FLOW_KEYFRAME_INTERVAL = 5
        config.OPTICAL_FLOW_COLOR_THRESHOLD = 50.0
        config.OPTICAL_FLOW_MOTION_THRESHOLD = 5.0
        return config
    
    @patch('src.infrastructure.processors.subtitle.native.PaddleOCR')
    @patch('src.infrastructure.utils.gpu_utils.require_gpu')
    @patch('src.core.config.get_config')
    @patch('psutil.Process')
    def test_uses_config_when_no_arguments(self, mock_process, mock_get_config, mock_require_gpu, mock_paddleocr, mock_config):
        """Test that SubtitleRemoverNative uses config values when arguments are None."""
        mock_get_config.return_value = mock_config
        
        # Mock psutil.Process
        mock_process_instance = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 1024 * 1024 * 100  # 100 MB
        mock_process_instance.memory_info.return_value = mock_memory_info
        mock_process.return_value = mock_process_instance
        
        # Mock PaddleOCR instance
        mock_ocr_instance = Mock()
        mock_paddleocr.return_value = mock_ocr_instance
        
        # Create instance without arguments
        instance = SubtitleRemoverNative()
        
        # Verify config was loaded
        mock_get_config.assert_called_once()
        
        # Verify instance uses config values
        assert instance.lang == mock_config.OCR_LANG
        assert instance.mask_dilation == mock_config.MASK_DILATION
        assert instance.confidence_threshold == mock_config.CONFIDENCE_THRESHOLD
        assert instance.use_optical_flow == mock_config.USE_OPTICAL_FLOW
        
        # Verify PaddleOCR was initialized with correct lang
        mock_paddleocr.assert_called_once()
        call_kwargs = mock_paddleocr.call_args[1]
        assert call_kwargs.get('lang') == mock_config.OCR_LANG
    
    @patch('src.infrastructure.processors.subtitle.native.PaddleOCR')
    @patch('src.infrastructure.utils.gpu_utils.require_gpu')
    @patch('src.core.config.get_config')
    @patch('psutil.Process')
    def test_argument_overrides_config(self, mock_process, mock_get_config, mock_require_gpu, mock_paddleocr, mock_config):
        """Test that arguments take priority over config values."""
        mock_get_config.return_value = mock_config
        
        # Mock psutil.Process
        mock_process_instance = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 1024 * 1024 * 100  # 100 MB
        mock_process_instance.memory_info.return_value = mock_memory_info
        mock_process.return_value = mock_process_instance
        
        # Mock PaddleOCR instance
        mock_ocr_instance = Mock()
        mock_paddleocr.return_value = mock_ocr_instance
        
        # Create instance with custom arguments
        custom_lang = "en"
        custom_dilation = 20
        custom_confidence = 0.5
        custom_optical_flow = True
        
        instance = SubtitleRemoverNative(
            lang=custom_lang,
            mask_dilation=custom_dilation,
            confidence_threshold=custom_confidence,
            use_optical_flow=custom_optical_flow
        )
        
        # Verify config was loaded
        mock_get_config.assert_called_once()
        
        # Verify instance uses argument values, not config values
        assert instance.lang == custom_lang
        assert instance.mask_dilation == custom_dilation
        assert instance.confidence_threshold == custom_confidence
        assert instance.use_optical_flow == custom_optical_flow
        
        # Verify PaddleOCR was initialized with custom lang
        mock_paddleocr.assert_called_once()
        call_kwargs = mock_paddleocr.call_args[1]
        assert call_kwargs.get('lang') == custom_lang
    
    @patch('src.infrastructure.processors.subtitle.native.PaddleOCR')
    @patch('src.infrastructure.utils.gpu_utils.require_gpu')
    @patch('src.core.config.get_config')
    @patch('psutil.Process')
    def test_partial_arguments(self, mock_process, mock_get_config, mock_require_gpu, mock_paddleocr, mock_config):
        """Test that some arguments can be provided while others use config."""
        mock_get_config.return_value = mock_config
        
        # Mock psutil.Process
        mock_process_instance = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 1024 * 1024 * 100  # 100 MB
        mock_process_instance.memory_info.return_value = mock_memory_info
        mock_process.return_value = mock_process_instance
        
        # Mock PaddleOCR instance
        mock_ocr_instance = Mock()
        mock_paddleocr.return_value = mock_ocr_instance
        
        # Create instance with only some arguments
        custom_lang = "fr"
        instance = SubtitleRemoverNative(lang=custom_lang)
        
        # Verify config was loaded
        mock_get_config.assert_called_once()
        
        # Verify mixed values
        assert instance.lang == custom_lang  # From argument
        assert instance.mask_dilation == mock_config.MASK_DILATION  # From config
        assert instance.confidence_threshold == mock_config.CONFIDENCE_THRESHOLD  # From config
        assert instance.use_optical_flow == mock_config.USE_OPTICAL_FLOW  # From config
        
        # Verify PaddleOCR was initialized with custom lang
        mock_paddleocr.assert_called_once()
        call_kwargs = mock_paddleocr.call_args[1]
        assert call_kwargs.get('lang') == custom_lang
    
    @patch('src.infrastructure.processors.subtitle.native.PaddleOCR')
    @patch('src.infrastructure.utils.gpu_utils.require_gpu')
    @patch('src.core.config.get_config')
    @patch('psutil.Process')
    def test_optical_flow_config_loaded(self, mock_process, mock_get_config, mock_require_gpu, mock_paddleocr, mock_config):
        """Test that optical flow config values are loaded when use_optical_flow is True."""
        mock_config.USE_OPTICAL_FLOW = True
        mock_get_config.return_value = mock_config
        
        # Mock psutil.Process
        mock_process_instance = Mock()
        mock_memory_info = Mock()
        mock_memory_info.rss = 1024 * 1024 * 100  # 100 MB
        mock_process_instance.memory_info.return_value = mock_memory_info
        mock_process.return_value = mock_process_instance
        
        # Mock PaddleOCR instance
        mock_ocr_instance = Mock()
        mock_paddleocr.return_value = mock_ocr_instance
        
        # Mock AnimatedTextDetector import
        with patch('src.infrastructure.detection.AnimatedTextDetector') as mock_detector:
            # Create instance with optical flow enabled
            instance = SubtitleRemoverNative(use_optical_flow=True)
            
            # Verify config values are stored
            assert hasattr(instance, '_animated_detector_config')
            assert instance._animated_detector_config['keyframe_interval'] == mock_config.OPTICAL_FLOW_KEYFRAME_INTERVAL
            assert instance._animated_detector_config['color_threshold'] == mock_config.OPTICAL_FLOW_COLOR_THRESHOLD
            assert instance._animated_detector_config['motion_threshold'] == mock_config.OPTICAL_FLOW_MOTION_THRESHOLD
    
    @patch('src.infrastructure.processors.subtitle.native.PaddleOCR')
    @patch('src.infrastructure.utils.gpu_utils.require_gpu')
    @patch('src.core.config.get_config')
    @patch('psutil.Process')
    def test_config_changes_affect_behavior(self, mock_process, mock_get_config, mock_require_gpu, mock_paddleocr, mock_config):
        """Test that changing config values affects SubtitleRemoverNative behavior."""
        # Test different config values
        test_cases = [
            {
                'OCR_LANG': 'en',
                'MASK_DILATION': 8,
                'CONFIDENCE_THRESHOLD': 0.3,
                'USE_OPTICAL_FLOW': False
            },
            {
                'OCR_LANG': 'ru',
                'MASK_DILATION': 15,
                'CONFIDENCE_THRESHOLD': 0.1,
                'USE_OPTICAL_FLOW': True
            },
            {
                'OCR_LANG': 'fr',
                'MASK_DILATION': 20,
                'CONFIDENCE_THRESHOLD': 0.5,
                'USE_OPTICAL_FLOW': False
            }
        ]
        
        for config_values in test_cases:
            # Update mock config
            for key, value in config_values.items():
                setattr(mock_config, key, value)
            
            mock_get_config.return_value = mock_config
            
            # Mock psutil.Process
            mock_process_instance = Mock()
            mock_memory_info = Mock()
            mock_memory_info.rss = 1024 * 1024 * 100  # 100 MB
            mock_process_instance.memory_info.return_value = mock_memory_info
            mock_process.return_value = mock_process_instance
            
            # Mock PaddleOCR instance
            mock_ocr_instance = Mock()
            mock_paddleocr.reset_mock()
            mock_paddleocr.return_value = mock_ocr_instance
            
            # Create instance without arguments
            instance = SubtitleRemoverNative()
            
            # Verify instance uses config values
            assert instance.lang == config_values['OCR_LANG']
            assert instance.mask_dilation == config_values['MASK_DILATION']
            assert instance.confidence_threshold == config_values['CONFIDENCE_THRESHOLD']
            assert instance.use_optical_flow == config_values['USE_OPTICAL_FLOW']
            
            # Verify PaddleOCR was initialized with correct lang
            mock_paddleocr.assert_called_once()
            call_kwargs = mock_paddleocr.call_args[1]
            assert call_kwargs.get('lang') == config_values['OCR_LANG']
