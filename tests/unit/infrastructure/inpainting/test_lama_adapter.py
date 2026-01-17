"""
Unit tests for LaMaAdapter.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import numpy as np
import torch

from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.core.config import get_config


class TestLaMaAdapter:
    """Unit tests for LaMaAdapter."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config.LAMA_MODEL_PATH = Path("/opt/lama_models/big-lama.pt")
        config.LAMA_TEMPORAL_SMOOTHING = True
        config.LAMA_SMOOTHING_WINDOW = 3
        config.LAMA_SMOOTHING_WEIGHTS = "0.2,0.6,0.2"
        config.FORCE_CPU = False
        config.MAX_HEIGHT = 1080
        config.AUTO_DOWNSCALE = True
        config.MAX_FRAMES_PER_CHUNK = 15
        config.PROPAINTER_OVERLAP = 2
        return config
    
    @pytest.fixture
    def adapter(self, mock_config):
        """Create a LaMaAdapter instance with mocked dependencies."""
        with patch('src.infrastructure.inpainting.lama_adapter.get_config', return_value=mock_config), \
             patch('src.infrastructure.inpainting.lama_adapter.Path.exists', return_value=True), \
             patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'):
            
            adapter = LaMaAdapter()
            adapter.model = Mock()
            adapter.device = 'cpu'
            adapter.batch_size = 4
            return adapter
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    def test_adapter_initialization(self, mock_exists, mock_get_config, mock_config):
        """Test that LaMaAdapter initializes with all components."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        # Mock component initialization
        with patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator') as mock_rc, \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy') as mock_sws, \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager') as mock_em, \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor') as mock_mp:
            
            # Mock EnvironmentManager.setup_gpu_environment
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
            adapter = LaMaAdapter()
            
            # Verify config was loaded
            mock_get_config.assert_called_once()
            assert adapter.config == mock_config
            
            # Verify components were initialized with config
            mock_rc.assert_called_once_with(mock_config)
            mock_sws.assert_called_once_with(mock_config)
            mock_em.assert_called_once_with(mock_config)
            mock_mp.assert_called_once_with(mock_config)
            
            # Verify component instances are stored
            assert adapter.res_calculator == mock_rc.return_value
            assert adapter.strategy == mock_sws.return_value
            assert adapter.env_manager == mock_em.return_value
            assert adapter.media_processor == mock_mp.return_value
            
            # Verify model path
            assert adapter.model_path == mock_config.LAMA_MODEL_PATH
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    def test_ensure_weights_download(self, mock_exists, mock_get_config, mock_config):
        """Test that weights are downloaded if missing."""
        mock_exists.return_value = False  # Weights don't exist
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.lama_adapter.gdown.download') as mock_gdown_download, \
             patch('src.infrastructure.inpainting.lama_adapter.Path.mkdir'), \
             patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'):
            
            adapter = LaMaAdapter()
            
            # Verify gdown.download was called to download weights (primary URL)
            # Note: The adapter tries primary URL first, then fallback
            mock_gdown_download.assert_called_once_with(
                "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",
                str(mock_config.LAMA_MODEL_PATH),
                quiet=False
            )
    
    def test_get_smoothing_weights(self, adapter):
        """Test getting smoothing weights."""
        weights = adapter._get_smoothing_weights()
        assert len(weights) == 3
        assert weights == [0.2, 0.6, 0.2]
        assert pytest.approx(sum(weights), 0.001) == 1.0
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    @patch('sys.path')
    @patch('builtins.__import__')
    def test_load_model_dummy_fallback(self, mock_import, mock_sys_path, mock_exists, mock_get_config, mock_config):
        """Test that dummy model is loaded when LaMa model is not available."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'), \
             patch('src.infrastructure.inpainting.lama_adapter.torch') as mock_torch:
            
            # Mock torch.cuda.is_available
            mock_torch.cuda.is_available.return_value = True
            mock_torch.device.return_value = 'cuda'
            
            # Mock torch.cuda.get_device_properties to return a mock with total_memory attribute
            mock_device_properties = Mock()
            mock_device_properties.total_memory = 8 * 1024**3  # 8 GB in bytes
            mock_torch.cuda.get_device_properties.return_value = mock_device_properties
            
            # Simulate ImportError when trying to import LaMa
            mock_import.side_effect = ImportError("No module named 'lama'")
            
            adapter = LaMaAdapter()
            adapter._load_model()
            
            # Verify dummy model was created
            assert adapter.model is not None
            assert adapter.device == 'cuda'
            assert hasattr(adapter.model, 'forward')
            # Verify batch size was adjusted based on VRAM
            assert adapter.batch_size == 6  # 8 GB VRAM -> batch size 6
    
    def test_apply_temporal_smoothing(self, adapter):
        """Test temporal smoothing functionality."""
        # Create test frames
        frames = [
            np.ones((100, 100, 3), dtype=np.uint8) * 100,
            np.ones((100, 100, 3), dtype=np.uint8) * 150,
            np.ones((100, 100, 3), dtype=np.uint8) * 200,
        ]
        
        # Apply smoothing
        smoothed = adapter._apply_temporal_smoothing(frames)
        
        # Verify output
        assert len(smoothed) == len(frames)
        assert smoothed[0].shape == frames[0].shape
        assert smoothed[0].dtype == np.uint8
        
        # Middle frame should be weighted average
        # 0.2*100 + 0.6*150 + 0.2*200 = 20 + 90 + 40 = 150
        assert np.mean(smoothed[1]) == pytest.approx(150, 1.0)
        
        # Test with disabled smoothing
        adapter.config.LAMA_TEMPORAL_SMOOTHING = False
        unsmoothed = adapter._apply_temporal_smoothing(frames)
        assert unsmoothed == frames
        
        # Test with less than 3 frames
        adapter.config.LAMA_TEMPORAL_SMOOTHING = True
        short_frames = frames[:2]
        result = adapter._apply_temporal_smoothing(short_frames)
        assert result == short_frames
    
    def test_pad_to_divisible_by_8(self, adapter):
        """Test padding to be divisible by 8."""
        # Test image that's already divisible by 8
        image_64 = np.ones((64, 64, 3), dtype=np.uint8) * 255
        padded, padding = adapter._pad_to_divisible_by_8(image_64)
        assert padded.shape == image_64.shape
        assert padding == (0, 0, 0, 0)
        
        # Test image that needs padding (63x63)
        image_63 = np.ones((63, 63, 3), dtype=np.uint8) * 255
        padded, padding = adapter._pad_to_divisible_by_8(image_63)
        assert padded.shape == (64, 64, 3)  # Padded to 64x64
        assert padding == (0, 1, 0, 1) or padding == (1, 0, 1, 0)  # Symmetric padding
        
        # Test grayscale mask
        mask_63 = np.ones((63, 63), dtype=np.uint8) * 255
        padded_mask, _ = adapter._pad_to_divisible_by_8(mask_63)
        assert padded_mask.shape == (64, 64)
    
    def test_unpad(self, adapter):
        """Test removing padding from image."""
        # Create a test image
        image = np.ones((64, 64, 3), dtype=np.uint8) * 255
        
        # Test with no padding
        unpadded = adapter._unpad(image, (0, 0, 0, 0))
        assert unpadded.shape == image.shape
        np.testing.assert_array_equal(unpadded, image)
        
        # Test with padding
        padded = np.pad(image, ((1, 2), (3, 4), (0, 0)), mode='constant')
        unpadded = adapter._unpad(padded, (1, 2, 3, 4))
        assert unpadded.shape == image.shape
        np.testing.assert_array_equal(unpadded, image)
    
    def test_inpaint_batch(self, adapter):
        """Test batch inpainting."""
        # Create test frames and masks
        frames = [
            np.ones((64, 64, 3), dtype=np.uint8) * 255,
            np.ones((64, 64, 3), dtype=np.uint8) * 128,
        ]
        masks = [
            np.zeros((64, 64), dtype=np.uint8),
            np.ones((64, 64), dtype=np.uint8) * 255,
        ]
        
        # Mock model forward
        mock_output = torch.ones((2, 3, 64, 64)) * 0.5
        adapter.model.return_value = mock_output
        
        # Test inpainting
        result = adapter._inpaint_batch(frames, masks)
        
        # Verify output
        assert len(result) == len(frames)
        assert result[0].shape == frames[0].shape
        assert result[0].dtype == np.uint8
        
        # Verify model was called
        adapter.model.assert_called_once()
        
        # Test with empty batch
        empty_result = adapter._inpaint_batch([], [])
        assert empty_result == []
    
    def test_inpaint_frame(self, adapter):
        """Test single frame inpainting."""
        frame = np.ones((64, 64, 3), dtype=np.uint8) * 255
        mask = np.zeros((64, 64), dtype=np.uint8)
        
        # Mock _inpaint_batch
        with patch.object(adapter, '_inpaint_batch') as mock_inpaint_batch:
            mock_inpaint_batch.return_value = [np.ones((64, 64, 3), dtype=np.uint8) * 128]
            
            result = adapter._inpaint_frame(frame, mask)
            
            # Verify _inpaint_batch was called with single frame
            mock_inpaint_batch.assert_called_once_with([frame], [mask])
            assert result.shape == frame.shape
            assert result.dtype == np.uint8
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    def test_process_method_mocked(self, mock_exists, mock_get_config, mock_config):
        """Test the main process method with mocked components."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator') as mock_rc, \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy') as mock_sws, \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager') as mock_em, \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor') as mock_mp, \
             patch('src.infrastructure.inpainting.lama_adapter.cv2') as mock_cv2, \
             patch('src.infrastructure.inpainting.lama_adapter.LaMaAdapter._inpaint_frame') as mock_inpaint:
            
            # Mock component instances
            mock_rc_instance = Mock()
            mock_rc_instance.calculate_optimal_params.return_value = (640, 480, 10)
            mock_rc.return_value = mock_rc_instance
            
            mock_sws_instance = Mock()
            mock_sws_instance.generate_chunks.return_value = [
                {
                    'frames_dir': Path('/tmp/frames1'),
                    'masks_dir': Path('/tmp/masks1'),
                    'output_dir': Path('/tmp/output1')
                }
            ]
            mock_sws.return_value = mock_sws_instance
            
            mock_em_instance = Mock()
            mock_em_instance.setup_gpu_environment.return_value = {
                'total_vram_gb': 8.0
            }
            mock_em.return_value = mock_em_instance
            
            mock_mp_instance = Mock()
            mock_mp_instance.prepare_input.return_value = Path('/tmp/frames')
            mock_mp_instance.get_frame_dimensions.return_value = (1920, 1080)
            mock_mp_instance.merge_chunks.return_value = Path('/tmp/final_output.mp4')
            mock_mp.return_value = mock_mp_instance
            
            # Mock CV2
            mock_cv2.imread.side_effect = [
                np.ones((480, 640, 3), dtype=np.uint8) * 255,  # frame
                np.zeros((480, 640), dtype=np.uint8),  # mask
            ]
            mock_cv2.IMREAD_GRAYSCALE = 0
            
            # Mock inpainting result
            mock_inpaint.return_value = np.ones((480, 640, 3), dtype=np.uint8) * 128
            
            # Create adapter and call process
            adapter = LaMaAdapter()
            result = adapter.process(
                input_path='/tmp/input.mp4',
                mask_dir=Path('/tmp/masks'),
                output_path=Path('/tmp/output.mp4')
            )
            
            # Verify component calls
            mock_mp_instance.prepare_input.assert_called_once_with('/tmp/input.mp4')
            # setup_gpu_environment is called twice: once in __init__ and once in process
            assert mock_em_instance.setup_gpu_environment.call_count == 2
            mock_rc_instance.calculate_optimal_params.assert_called_once_with(1920, 1080, 12.0)  # 8.0 * 1.5
            mock_sws_instance.generate_chunks.assert_called_once()
            mock_mp_instance.merge_chunks.assert_called_once()
            
            # Verify result
            assert result == Path('/tmp/final_output.mp4')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
