"""
Unit tests for SubtitleRemoverNative facade.
Tests orchestration, component integration, and configuration loading.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative


class MockConfig:
    """Mock configuration for testing."""
    def __init__(self):
        self.OCR_LANG = 'en'
        self.CONFIDENCE_THRESHOLD = 0.5
        self.USE_GPU_FOR_OCR = False
        self.ROI = "bottom"
        self.MASK_DILATION = 2
        self.MASK_BLUR = 1
        self.USE_MSER = True
        self.USE_GRADIENT = True


@pytest.fixture
def mock_config():
    """Fixture providing mock configuration."""
    return MockConfig()


@pytest.fixture
def mock_components():
    """Fixture mocking all components."""
    with patch('src.infrastructure.processors.subtitle.native.OcrEngine') as mock_ocr, \
         patch('src.infrastructure.processors.subtitle.native.MaskGenerator') as mock_mask, \
         patch('src.infrastructure.processors.subtitle.native.Inpainter') as mock_inpainter, \
         patch('src.infrastructure.processors.subtitle.native.TemporalFilter') as mock_temporal:
        
        # Create mock instances
        mock_ocr_instance = Mock()
        mock_mask_instance = Mock()
        mock_inpainter_instance = Mock()
        mock_temporal_instance = Mock()
        
        # Configure return values
        mock_ocr.return_value = mock_ocr_instance
        mock_mask.return_value = mock_mask_instance
        mock_inpainter.return_value = mock_inpainter_instance
        mock_temporal.return_value = mock_temporal_instance
        
        yield {
            'ocr': mock_ocr_instance,
            'mask': mock_mask_instance,
            'inpainter': mock_inpainter_instance,
            'temporal': mock_temporal_instance,
            'classes': {
                'OcrEngine': mock_ocr,
                'MaskGenerator': mock_mask,
                'Inpainter': mock_inpainter,
                'TemporalFilter': mock_temporal
            }
        }


@pytest.fixture
def tmp_dirs(tmp_path):
    """Fixture providing temporary directories for testing."""
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    
    input_dir.mkdir()
    output_dir.mkdir()
    
    # Create dummy image files
    for i in range(3):
        img_path = input_dir / f"frame_{i:03d}.png"
        # Create a simple 10x10 black image
        img_data = np.zeros((10, 10, 3), dtype=np.uint8)
        from PIL import Image
        Image.fromarray(img_data).save(str(img_path))
    
    return input_dir, output_dir


class TestSubtitleRemoverNative:
    """Test suite for SubtitleRemoverNative facade."""
    
    def test_initialization(self, mock_config, mock_components):
        """Test that SubtitleRemoverNative initializes correctly."""
        with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
            with patch('src.infrastructure.processors.subtitle.native.require_gpu') as mock_require_gpu:
                remover = SubtitleRemoverNative(mock_config)
                
                # Verify GPU requirement was checked
                mock_require_gpu.assert_called_once_with("subtitle removal (native)")
                
                # Verify components were initialized
                mock_components['classes']['OcrEngine'].assert_called_once_with(mock_config)
                mock_components['classes']['MaskGenerator'].assert_called_once_with(mock_config)
                mock_components['classes']['Inpainter'].assert_called_once_with(mock_config)
                mock_components['classes']['TemporalFilter'].assert_called_once_with(window_size=2)
                
                assert remover.config == mock_config
                assert remover.ocr == mock_components['ocr']
                assert remover.mask_gen == mock_components['mask']
                assert remover.inpainter == mock_components['inpainter']
                assert remover.temporal == mock_components['temporal']
    
    def test_initialization_default_config(self, mock_components):
        """Test initialization with default config (None)."""
        with patch('src.infrastructure.processors.subtitle.native.get_config') as mock_get_config:
            mock_config = MockConfig()
            mock_get_config.return_value = mock_config
            
            with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                remover = SubtitleRemoverNative()
                
                # Verify get_config was called
                mock_get_config.assert_called_once()
                
                # Verify components were initialized with config
                mock_components['classes']['OcrEngine'].assert_called_once_with(mock_config)
    
    def test_process_frames_orchestration(self, mock_config, mock_components, tmp_dirs):
        """Test that process_frames orchestrates components correctly."""
        input_dir, output_dir = tmp_dirs
        
        # Configure mock components
        mock_components['ocr'].detect_text.return_value = [
            (np.array([[1, 1], [5, 1], [5, 5], [1, 5]], dtype=np.float32), 0.9)
        ]
        mock_components['mask'].preprocess_for_ocr.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        mock_components['mask'].generate_mask.return_value = np.zeros((10, 10), dtype=np.uint8)
        mock_components['temporal'].process_batch.return_value = [
            np.zeros((10, 10), dtype=np.uint8),
            np.zeros((10, 10), dtype=np.uint8),
            np.zeros((10, 10), dtype=np.uint8)
        ]
        mock_components['inpainter'].inpaint.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        
        # Mock cv2.imread and cv2.imwrite
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    
                    # Run process_frames
                    remover.process_frames(input_dir, output_dir)
                    
                    # Verify cv2.imread was called for each frame
                    assert mock_imread.call_count == 3
                    
                    # Verify OCR was called for each frame
                    assert mock_components['ocr'].detect_text.call_count == 3
                    
                    # Verify mask generation was called for each frame
                    assert mock_components['mask'].generate_mask.call_count == 3
                    
                    # Verify temporal filtering was called once with all masks
                    mock_components['temporal'].process_batch.assert_called_once()
                    assert len(mock_components['temporal'].process_batch.call_args[0][0]) == 3
                    
                    # Verify inpainting was called for each frame
                    assert mock_components['inpainter'].inpaint.call_count == 3
                    
                    # Verify cv2.imwrite was called for each frame
                    assert mock_imwrite.call_count == 3
    
    def test_process_frames_empty_mask(self, mock_config, mock_components, tmp_dirs):
        """Test process_frames with empty mask (no text detected)."""
        input_dir, output_dir = tmp_dirs
        
        # Configure mock to return empty mask
        mock_components['ocr'].detect_text.return_value = []
        mock_components['mask'].generate_mask.return_value = np.zeros((10, 10), dtype=np.uint8)
        mock_components['temporal'].process_batch.return_value = [
            np.zeros((10, 10), dtype=np.uint8),
            np.zeros((10, 10), dtype=np.uint8),
            np.zeros((10, 10), dtype=np.uint8)
        ]
        
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    remover.process_frames(input_dir, output_dir)
                    
                    # When mask is empty, inpainter should NOT be called
                    # Instead, original image should be saved
                    assert mock_components['inpainter'].inpaint.call_count == 0
                    
                    # But cv2.imwrite should still be called
                    assert mock_imwrite.call_count == 3
    
    def test_process_frames_error_handling(self, mock_config, mock_components, tmp_dirs):
        """Test error handling during frame processing."""
        input_dir, output_dir = tmp_dirs
        
        # Make OCR fail for first frame
        mock_components['ocr'].detect_text.side_effect = [
            Exception("OCR failed"),
            [],  # Empty for second frame
            [(np.array([[1, 1], [5, 1], [5, 5], [1, 5]], dtype=np.float32), 0.9)]
        ]
        
        mock_components['mask'].generate_mask.side_effect = [
            np.zeros((10, 10), dtype=np.uint8),  # Empty mask for error case
            np.zeros((10, 10), dtype=np.uint8),  # Empty mask for empty OCR
            np.ones((10, 10), dtype=np.uint8) * 255  # Full mask for third frame
        ]
        
        mock_components['temporal'].process_batch.return_value = [
            np.zeros((10, 10), dtype=np.uint8),
            np.zeros((10, 10), dtype=np.uint8),
            np.ones((10, 10), dtype=np.uint8) * 255
        ]
        
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite, \
             patch('src.infrastructure.processors.subtitle.native.logger') as mock_logger:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    remover.process_frames(input_dir, output_dir)
                    
                    # Verify error was logged
                    assert mock_logger.error.called
                    
                    # Verify processing continued for all frames
                    assert mock_imwrite.call_count == 3
    
    def test_process_single_frame(self, mock_config, mock_components, tmp_path):
        """Test single frame processing."""
        input_path = tmp_path / "input.png"
        output_path = tmp_path / "output.png"
        
        # Create dummy image
        img_data = np.zeros((10, 10, 3), dtype=np.uint8)
        from PIL import Image
        Image.fromarray(img_data).save(str(input_path))
        
        # Configure mocks
        mock_components['ocr'].detect_text.return_value = [
            (np.array([[1, 1], [5, 1], [5, 5], [1, 5]], dtype=np.float32), 0.9)
        ]
        mock_components['mask'].preprocess_for_ocr.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        mock_components['mask'].generate_mask.return_value = np.ones((10, 10), dtype=np.uint8) * 255
        mock_components['inpainter'].inpaint.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
        
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    remover.process_single_frame(input_path, output_path)
                    
                    # Verify pipeline was executed
                    mock_imread.assert_called_once_with(str(input_path))
                    mock_components['ocr'].detect_text.assert_called_once()
                    mock_components['mask'].generate_mask.assert_called_once()
                    mock_components['inpainter'].inpaint.assert_called_once()
                    mock_imwrite.assert_called_once_with(str(output_path), mock_components['inpainter'].inpaint.return_value)
    
    def test_process_single_frame_no_text(self, mock_config, mock_components, tmp_path):
        """Test single frame processing with no text detected."""
        input_path = tmp_path / "input.png"
        output_path = tmp_path / "output.png"
        
        # Create dummy image
        img_data = np.zeros((10, 10, 3), dtype=np.uint8)
        from PIL import Image
        Image.fromarray(img_data).save(str(input_path))
        
        # Configure OCR to return empty result
        mock_components['ocr'].detect_text.return_value = []
        
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    remover.process_single_frame(input_path, output_path)
                    
                    # When no text detected, mask generation and inpainting should be skipped
                    mock_components['mask'].generate_mask.assert_not_called()
                    mock_components['inpainter'].inpaint.assert_not_called()
                    
                    # Original image should be saved
                    mock_imwrite.assert_called_once_with(str(output_path), mock_imread.return_value)
    
    def test_chunk_method(self, mock_config):
        """Test the _chunk helper method."""
        with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
            with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                remover = SubtitleRemoverNative(mock_config)
                
                items = [1, 2, 3, 4, 5, 6, 7]
                chunks = list(remover._chunk(items, 3))
                
                assert chunks == [[1, 2, 3], [4, 5, 6], [7]]
    
    def test_cleanup(self, mock_config, mock_components):
        """Test cleanup method."""
        with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
            with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                remover = SubtitleRemoverNative(mock_config)
                
                # Call cleanup
                remover.cleanup()
                
                # Verify OCR cleanup was called
                mock_components['ocr'].cleanup.assert_called_once()
    
    def test_memory_monitoring(self, mock_config, mock_components, tmp_dirs):
        """Test memory monitoring during batch processing."""
        input_dir, output_dir = tmp_dirs
        
        # Create more frames to test batching
        for i in range(3, 8):
            img_path = input_dir / f"frame_{i:03d}.png"
            img_data = np.zeros((10, 10, 3), dtype=np.uint8)
            from PIL import Image
            Image.fromarray(img_data).save(str(img_path))
        
        # Configure mocks
        mock_components['ocr'].detect_text.return_value = []
        mock_components['mask'].generate_mask.return_value = np.zeros((10, 10), dtype=np.uint8)
        mock_components['temporal'].process_batch.return_value = [
            np.zeros((10, 10), dtype=np.uint8) for _ in range(8)
        ]
        
        with patch('src.infrastructure.processors.subtitle.native.cv2.imread') as mock_imread, \
             patch('src.infrastructure.processors.subtitle.native.cv2.imwrite') as mock_imwrite, \
             patch('src.infrastructure.processors.subtitle.native.psutil.Process') as mock_process, \
             patch('src.infrastructure.processors.subtitle.native.gc.collect') as mock_gc:
            
            mock_imread.return_value = np.zeros((10, 10, 3), dtype=np.uint8)
            
            # Mock memory info
            mock_memory = Mock()
            mock_memory.rss = 500 * 1024 * 1024  # 500 MB
            mock_process_instance = Mock()
            mock_process_instance.memory_info.return_value = mock_memory
            mock_process.return_value = mock_process_instance
            
            with patch('src.infrastructure.processors.subtitle.native.get_config', return_value=mock_config):
                with patch('src.infrastructure.processors.subtitle.native.require_gpu'):
                    remover = SubtitleRemoverNative(mock_config)
                    remover.process_frames(input_dir, output_dir)
                    
                    # Verify garbage collection was called
                    mock_gc.assert_called()
                    
                    # Verify memory monitoring occurred
                    assert mock_process_instance.memory_info.called


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
