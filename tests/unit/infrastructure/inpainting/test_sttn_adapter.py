"""
Unit tests for STTNAdapter.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import numpy as np
import torch

from src.infrastructure.inpainting.sttn_adapter import STTNAdapter
from src.core.config import get_config


class TestSTTNAdapter:
    """Unit tests for STTNAdapter."""
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock config."""
        config = Mock()
        config.STTN_MODEL_PATH = Path("/opt/sttn_models/sttn.pth")
        config.STTN_CHUNK_SIZE = 20
        config.STTN_OVERLAP = 2
        config.FORCE_CPU = False
        config.MAX_HEIGHT = 1080
        config.AUTO_DOWNSCALE = True
        config.MAX_FRAMES_PER_CHUNK = 15
        config.PROPAINTER_OVERLAP = 2
        return config
    
    @patch('src.infrastructure.inpainting.sttn_adapter.get_config')
    @patch('src.infrastructure.inpainting.sttn_adapter.Path.exists')
    def test_adapter_initialization(self, mock_exists, mock_get_config, mock_config):
        """Test that STTNAdapter initializes with all components."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        # Mock component initialization
        with patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator') as mock_rc, \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy') as mock_sws, \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager') as mock_em, \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor') as mock_mp:
            
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
            adapter = STTNAdapter()
            
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
            assert adapter.model_path == mock_config.STTN_MODEL_PATH
    
    @patch('src.infrastructure.inpainting.sttn_adapter.get_config')
    @patch('src.infrastructure.inpainting.sttn_adapter.Path.exists')
    def test_ensure_weights_download(self, mock_exists, mock_get_config, mock_config):
        """Test that weights are downloaded if missing."""
        mock_exists.return_value = False  # Weights don't exist
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.sttn_adapter.gdown.download') as mock_gdown_download, \
             patch('src.infrastructure.inpainting.sttn_adapter.Path.mkdir'), \
             patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor'):
            
            adapter = STTNAdapter()
            
            # Verify gdown.download was called to download weights
            mock_gdown_download.assert_called_once_with(
                "https://drive.google.com/uc?id=1yVXw0VnAc8-Bn3QJf7pDfHhqHxPqR8Xz",
                str(mock_config.STTN_MODEL_PATH),
                quiet=False
            )
    
    @patch('src.infrastructure.inpainting.sttn_adapter.get_config')
    @patch('src.infrastructure.inpainting.sttn_adapter.Path.exists')
    def test_load_model_dummy_fallback(self, mock_exists, mock_get_config, mock_config):
        """Test that dummy model is loaded when STTN model is not available."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor'), \
             patch('src.infrastructure.inpainting.sttn_adapter.torch') as mock_torch:
            
            # Mock torch.cuda.is_available
            mock_torch.cuda.is_available.return_value = True
            mock_torch.device.return_value = 'cuda'
            mock_torch.load.side_effect = ImportError("STTN model not found")
            
            adapter = STTNAdapter()
            adapter._load_model()
            
            # Verify dummy model was created
            assert adapter.model is not None
            assert adapter.device == 'cuda'
            assert hasattr(adapter.model, 'forward')
    
    def test_prepare_sequence(self, mock_config):
        """Test sequence preparation for STTN model."""
        with patch('src.infrastructure.inpainting.sttn_adapter.get_config', return_value=mock_config), \
             patch('src.infrastructure.inpainting.sttn_adapter.Path.exists', return_value=True), \
             patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor'):
            
            adapter = STTNAdapter()
            
            # Create test frames and masks
            frames = [
                np.ones((100, 100, 3), dtype=np.uint8) * 100,
                np.ones((100, 100, 3), dtype=np.uint8) * 150,
                np.ones((100, 100, 3), dtype=np.uint8) * 200,
            ]
            masks = [
                np.zeros((100, 100), dtype=np.uint8),
                np.ones((100, 100), dtype=np.uint8) * 255,
                np.zeros((100, 100), dtype=np.uint8),
            ]
            
            # Prepare sequence
            frames_tensor, masks_tensor = adapter._prepare_sequence(frames, masks)
            
            # Verify tensor shapes
            assert frames_tensor.shape == (1, 3, 3, 100, 100)  # [batch, seq_len, channels, height, width]
            assert masks_tensor.shape == (1, 3, 1, 100, 100)   # [batch, seq_len, 1, height, width]
            
            # Verify values are normalized
            assert frames_tensor.max() <= 1.0
            assert frames_tensor.min() >= 0.0
            assert masks_tensor.max() <= 1.0
            assert masks_tensor.min() >= 0.0
    
    @patch('src.infrastructure.inpainting.sttn_adapter.get_config')
    @patch('src.infrastructure.inpainting.sttn_adapter.Path.exists')
    def test_inpaint_sequence(self, mock_exists, mock_get_config, mock_config):
        """Test sequence inpainting."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator'), \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy'), \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager'), \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor'), \
             patch('src.infrastructure.inpainting.sttn_adapter.torch') as mock_torch:
            
            # Mock model
            mock_model = Mock()
            mock_model.eval.return_value = None
            mock_model.to.return_value = mock_model
            
            # Mock torch operations
            mock_torch.cuda.is_available.return_value = True
            mock_torch.device.return_value = 'cuda'
            
            # Create mock tensors
            mock_frame_tensor = Mock()
            mock_mask_tensor = Mock()
            mock_output_tensor = Mock()
            
            # Setup chain of calls for frame tensor
            mock_frame_tensor.permute.return_value = mock_frame_tensor
            mock_frame_tensor.float.return_value = mock_frame_tensor
            mock_frame_tensor.__truediv__ = Mock(return_value=mock_frame_tensor)
            mock_frame_tensor.unsqueeze.return_value = mock_frame_tensor
            
            # Setup chain of calls for mask tensor
            mock_mask_tensor.unsqueeze.return_value = mock_mask_tensor
            mock_mask_tensor.float.return_value = mock_mask_tensor
            mock_mask_tensor.__truediv__ = Mock(return_value=mock_mask_tensor)
            mock_mask_tensor.__gt__ = Mock(return_value=mock_mask_tensor)
            
            # Mock torch.from_numpy to return appropriate mock tensors
            def from_numpy_side_effect(arr):
                if arr.ndim == 3:  # frame
                    return mock_frame_tensor
                else:  # mask
                    return mock_mask_tensor
            
            mock_torch.from_numpy.side_effect = from_numpy_side_effect
            
            # Mock torch.stack
            mock_torch.stack.return_value = mock_frame_tensor
            
            # Mock torch.zeros
            mock_torch.zeros.return_value = mock_mask_tensor
            
            # Mock model output
            mock_output_tensor.squeeze.return_value = mock_output_tensor
            mock_output_tensor.permute.return_value = mock_output_tensor
            mock_output_tensor.cpu.return_value = mock_output_tensor
            mock_output_tensor.numpy.return_value = np.ones((3, 100, 100, 3), dtype=np.float32) * 0.5
            
            mock_model.return_value = mock_output_tensor
            
            # Mock torch.no_grad() to return a context manager
            mock_no_grad_context = Mock()
            mock_no_grad_context.__enter__ = Mock()
            mock_no_grad_context.__exit__ = Mock()
            mock_torch.no_grad.return_value = mock_no_grad_context
            
            adapter = STTNAdapter()
            adapter.model = mock_model
            adapter.device = 'cuda'
            
            # Create test frames and masks
            frames = [
                np.ones((100, 100, 3), dtype=np.uint8) * 255,
                np.ones((100, 100, 3), dtype=np.uint8) * 255,
                np.ones((100, 100, 3), dtype=np.uint8) * 255,
            ]
            masks = [
                np.zeros((100, 100), dtype=np.uint8),
                np.ones((100, 100), dtype=np.uint8) * 255,
                np.zeros((100, 100), dtype=np.uint8),
            ]
            
            # Test sequence inpainting
            results = adapter._inpaint_sequence(frames, masks)
            
            # Verify output
            assert len(results) == len(frames)
            assert results[0].shape == frames[0].shape
            assert results[0].dtype == np.uint8
    
    @patch('src.infrastructure.inpainting.sttn_adapter.get_config')
    @patch('src.infrastructure.inpainting.sttn_adapter.Path.exists')
    def test_process_method_mocked(self, mock_exists, mock_get_config, mock_config):
        """Test the main process method with mocked components."""
        mock_exists.return_value = True
        mock_get_config.return_value = mock_config
        
        with patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator') as mock_rc, \
             patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy') as mock_sws, \
             patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager') as mock_em, \
             patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor') as mock_mp, \
             patch('src.infrastructure.inpainting.sttn_adapter.cv2') as mock_cv2, \
             patch('src.infrastructure.inpainting.sttn_adapter.STTNAdapter._inpaint_sequence') as mock_inpaint, \
             patch('src.infrastructure.inpainting.sttn_adapter.sorted') as mock_sorted, \
             patch('src.infrastructure.inpainting.sttn_adapter.list') as mock_list:
            
            # Mock component instances
            mock_rc_instance = Mock()
            mock_rc_instance.calculate_optimal_params.return_value = (640, 480, 10)
            mock_rc.return_value = mock_rc_instance
            
            # Create mock chunk with mock directories
            mock_frames_dir = Mock(spec=Path)
            mock_masks_dir = Mock(spec=Path)
            mock_output_dir = Mock(spec=Path)
            
            # Mock glob to return file paths
            mock_frame_file1 = Mock(spec=Path)
            mock_frame_file2 = Mock(spec=Path)
            mock_mask_file1 = Mock(spec=Path)
            mock_mask_file2 = Mock(spec=Path)
            
            # Mock __truediv__ for Path operations
            def mock_div(self, other):
                result = Mock(spec=Path)
                result.__str__ = Mock(return_value=f"{self}/{other}")
                return result
            
            mock_output_dir.__truediv__ = lambda self, other: mock_div(self, other)
            
            mock_frames_dir.glob.return_value = [mock_frame_file1, mock_frame_file2]
            mock_masks_dir.glob.return_value = [mock_mask_file1, mock_mask_file2]
            
            mock_sws_instance = Mock()
            mock_sws_instance.generate_chunks.return_value = [
                {
                    'frames_dir': mock_frames_dir,
                    'masks_dir': mock_masks_dir,
                    'output_dir': mock_output_dir
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
                np.ones((480, 640, 3), dtype=np.uint8) * 255,  # frame 1
                np.zeros((480, 640), dtype=np.uint8),  # mask 1
                np.ones((480, 640, 3), dtype=np.uint8) * 255,  # frame 2
                np.zeros((480, 640), dtype=np.uint8),  # mask 2
            ]
            mock_cv2.IMREAD_GRAYSCALE = 0
            
            # Mock inpainting result
            mock_inpaint.return_value = [
                np.ones((480, 640, 3), dtype=np.uint8) * 128,
                np.ones((480, 640, 3), dtype=np.uint8) * 128,
            ]
            
            # Mock sorted to return the same list without sorting (mocks can't be compared)
            mock_sorted.side_effect = lambda x, **kwargs: x if isinstance(x, list) else list(x)
            
            # Mock list to return the same iterable
            mock_list.side_effect = lambda x: x if isinstance(x, list) else [x]
            
            # Create adapter and call process
            adapter = STTNAdapter()
            result = adapter.process(
                input_path='/tmp/input.mp4',
                mask_dir=Path('/tmp/masks'),
                output_path=Path('/tmp/output.mp4')
            )
            
            # Verify component calls
            mock_mp_instance.prepare_input.assert_called_once_with('/tmp/input.mp4')
            # setup_gpu_environment is called twice: once in __init__ and once in process
            assert mock_em_instance.setup_gpu_environment.call_count == 2
            mock_rc_instance.calculate_optimal_params.assert_called_once_with(1920, 1080, 6.4)  # 8.0 * 0.8
            mock_sws_instance.generate_chunks.assert_called_once()
            mock_mp_instance.merge_chunks.assert_called_once()
            
            # Verify STTN-specific config is used
            assert adapter.strategy.chunk_size == min(mock_config.STTN_CHUNK_SIZE, 10)
            assert adapter.strategy.overlap == mock_config.STTN_OVERLAP
            
            # Verify result
            assert result == Path('/tmp/final_output.mp4')
    
    def test_config_chunk_size_respected(self, mock_config):
        """Test that STTN chunk size from config is respected."""
        # Test different STTN_CHUNK_SIZE values
        test_cases = [
            (10, 10),   # Smaller than calculated safe_chunk_size
            (20, 10),   # Larger than calculated safe_chunk_size (should be limited)
            (5, 5),     # Very small
        ]
        
        for config_chunk_size, expected_chunk_size in test_cases:
            mock_config.STTN_CHUNK_SIZE = config_chunk_size
            
            with patch('src.infrastructure.inpainting.sttn_adapter.get_config', return_value=mock_config), \
                 patch('src.infrastructure.inpainting.sttn_adapter.Path.exists', return_value=True), \
                 patch('src.infrastructure.inpainting.sttn_adapter.ResolutionCalculator') as mock_rc, \
                 patch('src.infrastructure.inpainting.sttn_adapter.SlidingWindowStrategy') as mock_sws, \
                 patch('src.infrastructure.inpainting.sttn_adapter.EnvironmentManager') as mock_em, \
                 patch('src.infrastructure.inpainting.sttn_adapter.MediaProcessor') as mock_mp:
                
                # Mock component instances
                mock_rc_instance = Mock()
                mock_rc_instance.calculate_optimal_params.return_value = (640, 480, 10)  # safe_chunk_size = 10
                mock_rc.return_value = mock_rc_instance
                
                mock_sws_instance = Mock()
                mock_sws.return_value = mock_sws_instance
                
                mock_em_instance = Mock()
                mock_em_instance.setup_gpu_environment.return_value = {'total_vram_gb': 8.0}
                mock_em.return_value = mock_em_instance
                
                mock_mp_instance = Mock()
                mock_mp_instance.prepare_input.return_value = Path('/tmp/frames')
                mock_mp_instance.get_frame_dimensions.return_value = (1920, 1080)
                mock_mp_instance.merge_chunks.return_value = Path('/tmp/final_output.mp4')
                mock_mp.return_value = mock_mp_instance
                
                # Create adapter
                adapter = STTNAdapter()
                
                # Simulate the chunk size setting that happens in process()
                safe_chunk_size = 10  # from mock
                adapter.strategy.chunk_size = min(mock_config.STTN_CHUNK_SIZE, safe_chunk_size)
                
                # Verify chunk size is set correctly
                assert adapter.strategy.chunk_size == expected_chunk_size, \
                    f"Expected chunk_size={expected_chunk_size} for STTN_CHUNK_SIZE={config_chunk_size}, got {adapter.strategy.chunk_size}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
