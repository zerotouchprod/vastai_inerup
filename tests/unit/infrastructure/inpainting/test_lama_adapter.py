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
            
            # Verify gdown.download was called to download weights
            mock_gdown_download.assert_called_once_with(
                "https://drive.google.com/uc?id=1t5K7U8lHx2-MsLGhMEdU-qV7gvMfU9bF",
                str(mock_config.LAMA_MODEL_PATH),
                quiet=False
            )
    
    def test_parse_smoothing_weights(self, mock_config):
        """Test parsing of smoothing weights from config string."""
        with patch('src.infrastructure.inpainting.lama_adapter.get_config', return_value=mock_config), \
             patch('src.infrastructure.inpainting.lama_adapter.Path.exists', return_value=True), \
             patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'):
            
            adapter = LaMaAdapter()
            
            # Test default weights
            weights = adapter._parse_smoothing_weights()
            assert len(weights) == 3
            assert pytest.approx(sum(weights), 0.001) == 1.0
            assert weights[0] == pytest.approx(0.2, 0.001)
            assert weights[1] == pytest.approx(0.6, 0.001)
            assert weights[2] == pytest.approx(0.2, 0.001)
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    def test_load_model_dummy_fallback(self, mock_exists, mock_get_config, mock_config):
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
            mock_torch.load.side_effect = ImportError("LaMa model not found")
            
            adapter = LaMaAdapter()
            adapter._load_model()
            
            # Verify dummy model was created
            assert adapter.model is not None
            assert adapter.device == 'cuda'
            assert hasattr(adapter.model, 'forward')
    
    def test_apply_temporal_smoothing(self, mock_config):
        """Test temporal smoothing functionality."""
        with patch('src.infrastructure.inpainting.lama_adapter.get_config', return_value=mock_config), \
             patch('src.infrastructure.inpainting.lama_adapter.Path.exists', return_value=True), \
             patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'):
            
            adapter = LaMaAdapter()
            
            # Create test frames
            frames = [
                np.ones((100, 100, 3), dtype=np.uint8) * 100,
                np.ones((100, 100, 3), dtype=np.uint8) * 150,
                np.ones((100, 100, 3), dtype=np.uint8) * 200,
            ]
            
            # Apply smoothing
            smoothed = adapter._apply_temporal_smoothing(frames, [])
            
            # Verify output
            assert len(smoothed) == len(frames)
            assert smoothed[0].shape == frames[0].shape
            assert smoothed[0].dtype == np.uint8
            
            # Middle frame should be weighted average
            # 0.2*100 + 0.6*150 + 0.2*200 = 20 + 90 + 40 = 150
            assert np.mean(smoothed[1]) == pytest.approx(150, 1.0)
    
    @patch('src.infrastructure.inpainting.lama_adapter.get_config')
    @patch('src.infrastructure.inpainting.lama_adapter.Path.exists')
    def test_inpaint_frame(self, mock_exists, mock_get_config, mock_config):
        """Test single frame inpainting."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.lama_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.lama_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.lama_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.lama_adapter.MediaProcessor'), \
             patch('src.infrastructure.inpainting.lama_adapter.torch') as mock_torch:
            
            # Mock model
            mock_model = Mock()
            mock_model.eval.return_value = None
            mock_model.to.return_value = mock_model
            
            # Mock torch operations
            mock_torch.cuda.is_available.return_value = False  # Force CPU
            mock_torch.device.return_value = 'cpu'
            
            # Create mock tensors
            mock_frame_tensor = Mock()
            mock_mask_tensor = Mock()
            mock_output_tensor = Mock()
            
            # Setup chain of calls
            mock_frame_tensor.permute.return_value = mock_frame_tensor
            mock_frame_tensor.float.return_value = mock_frame_tensor
            mock_frame_tensor.unsqueeze.return_value = mock_frame_tensor
            mock_frame_tensor.to.return_value = mock_frame_tensor
            mock_frame_tensor.__truediv__ = Mock(return_value=mock_frame_tensor)
            
            mock_mask_tensor.unsqueeze.return_value = mock_mask_tensor
            mock_mask_tensor.float.return_value = mock_mask_tensor
            mock_mask_tensor.to.return_value = mock_mask_tensor
            mock_mask_tensor.__gt__ = Mock(return_value=mock_mask_tensor)
            mock_mask_tensor.__truediv__ = Mock(return_value=mock_mask_tensor)
            
            mock_output_tensor.squeeze.return_value = mock_output_tensor
            mock_output_tensor.permute.return_value = mock_output_tensor
            mock_output_tensor.cpu.return_value = mock_output_tensor
            mock_output_tensor.numpy.return_value = np.ones((100, 100, 3), dtype=np.uint8) * 128
            
            mock_model.return_value = mock_output_tensor
            
            # Mock torch.from_numpy to return our mock tensors
            def from_numpy_side_effect(arr):
                if arr.ndim == 3:  # frame
                    return mock_frame_tensor
                else:  # mask
                    return mock_mask_tensor
            
            mock_torch.from_numpy.side_effect = from_numpy_side_effect
            
            # Mock torch.no_grad() to return a context manager
            mock_no_grad_context = Mock()
            mock_no_grad_context.__enter__ = Mock()
            mock_no_grad_context.__exit__ = Mock()
            mock_torch.no_grad.return_value = mock_no_grad_context
            
            adapter = LaMaAdapter()
            adapter.model = mock_model
            adapter.device = 'cpu'  # Use CPU to avoid CUDA issues
            
            # Create test frame and mask
            frame = np.ones((100, 100, 3), dtype=np.uint8) * 255
            mask = np.zeros((100, 100), dtype=np.uint8)
            mask[50:70, 50:70] = 255  # Small mask in center
            
            # Test inpainting
            result = adapter._inpaint_frame(frame, mask)
            
            # Verify output shape and type
            assert result.shape == frame.shape
            assert result.dtype == np.uint8
            
            # Verify model was called
            assert mock_model.called
    
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
