"""
Tests for refactored subtitle removal module.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import numpy as np

from src.core.config import AppConfig
from src.domain.models import InpaintingRequest, ProcessingResult
from src.services.cleaner_service import SubtitleRemoverService
from src.services.mask_service import MaskGeneratorService
from src.services.wrapper import SubtitleRemoverProPainterWrapper


class TestConfig:
    """Test configuration module."""
    
    def test_app_config_defaults(self):
        """Test AppConfig default values."""
        config = AppConfig()
        
        assert config.OCR_LANG == "en"
        assert config.MASK_DILATION == 12
        assert config.USE_GPU is True
        assert config.USE_GPU_FOR_OCR is False
        assert config.CONFIDENCE_THRESHOLD == 0.3
        assert str(config.PROPAINTER_ROOT) == "/opt/ProPainter"
    
    def test_app_config_env_override(self, monkeypatch):
        """Test AppConfig environment variable override."""
        monkeypatch.setenv("OCR_LANG", "ru")
        monkeypatch.setenv("MASK_DILATION", "8")
        monkeypatch.setenv("USE_GPU", "false")
        
        config = AppConfig()
        
        assert config.OCR_LANG == "ru"
        assert config.MASK_DILATION == 8
        assert config.USE_GPU is False


class TestDomainModels:
    """Test domain models."""
    
    def test_inpainting_request(self):
        """Test InpaintingRequest model."""
        input_dir = Path("/tmp/input")
        output_dir = Path("/tmp/output")
        
        request = InpaintingRequest(
            input_dir=input_dir,
            output_dir=output_dir
        )
        
        assert request.input_dir == input_dir
        assert request.output_dir == output_dir
    
    def test_processing_result(self):
        """Test ProcessingResult model."""
        result = ProcessingResult(
            success=True,
            output_path=Path("/tmp/output"),
            frames_processed=100,
            errors=[]
        )
        
        assert result.success is True
        assert result.frames_processed == 100
        assert len(result.errors) == 0


class TestMaskService:
    """Test mask generation service."""
    
    @pytest.fixture
    def mock_ocr_wrapper(self):
        """Mock OCR wrapper."""
        with patch('src.services.mask_service.ThreadSafeOCR') as mock:
            instance = Mock()
            instance.create_masks_for_directory.return_value = Path("/tmp/masks")
            instance.process_batch.return_value = [np.zeros((100, 100), dtype=np.uint8)]
            mock.return_value = instance
            yield mock
    
    def test_mask_service_init(self, mock_ocr_wrapper):
        """Test MaskGeneratorService initialization."""
        service = MaskGeneratorService(
            lang="ru",
            mask_dilation=8,
            use_gpu_for_ocr=True,
            confidence_threshold=0.5
        )
        
        assert service.lang == "ru"
        assert service.mask_dilation == 8
        assert service.use_gpu_for_ocr is True
        assert service.confidence_threshold == 0.5
        mock_ocr_wrapper.assert_called_once()
    
    def test_generate_masks(self, mock_ocr_wrapper, tmp_path):
        """Test generate_masks method."""
        service = MaskGeneratorService()
        
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        
        # Create dummy image
        dummy_image = input_dir / "frame1.png"
        dummy_image.write_bytes(b"dummy")
        
        result = service.generate_masks(input_dir, output_dir)
        
        assert result == output_dir
        mock_ocr_wrapper.return_value.create_masks_for_directory.assert_called_once()


class TestCleanerService:
    """Test cleaner service."""
    
    @pytest.fixture
    def mock_dependencies(self):
        """Mock all dependencies for cleaner service."""
        with patch('src.services.cleaner_service.get_config') as mock_config, \
             patch('src.services.cleaner_service.get_device_manager') as mock_device_mgr, \
             patch('src.services.cleaner_service.MaskGeneratorService') as mock_mask_service, \
             patch('src.services.cleaner_service.ProPainterLoader') as mock_loader, \
             patch('src.services.cleaner_service.read_video') as mock_read_video, \
             patch('src.services.cleaner_service.save_frames') as mock_save_frames:
            
            # Mock config
            config = Mock()
            config.OCR_LANG = "en"
            config.MASK_DILATION = 12
            config.USE_GPU = True
            config.USE_GPU_FOR_OCR = False
            config.CONFIDENCE_THRESHOLD = 0.3
            config.BATCH_SIZE = 8
            mock_config.return_value = config
            
            # Mock device manager
            device_mgr = Mock()
            device_mgr.get_device.return_value = Mock()
            device_mgr.estimate_max_batch_size.return_value = 30
            mock_device_mgr.return_value = device_mgr
            
            # Mock mask service
            mask_service = Mock()
            mask_service.generate_masks.return_value = Path("/tmp/masks")
            mask_service.cleanup_temp_dir.return_value = None
            mock_mask_service.return_value = mask_service
            
            # Mock ProPainter loader
            loader = Mock()
            loader.is_available.return_value = True
            loader.load_model.return_value = Mock()
            mock_loader.return_value = loader
            
            # Mock video reading
            mock_read_video.return_value = (
                np.random.randint(0, 255, (10, 100, 100, 3), dtype=np.uint8),
                30.0
            )
            
            yield {
                'config': mock_config,
                'device_mgr': mock_device_mgr,
                'mask_service': mock_mask_service,
                'loader': mock_loader,
                'read_video': mock_read_video,
                'save_frames': mock_save_frames
            }
    
    def test_cleaner_service_init(self, mock_dependencies):
        """Test SubtitleRemoverService initialization."""
        service = SubtitleRemoverService(
            lang="ru",
            mask_dilation=8,
            use_gpu=False
        )
        
        assert service.lang == "ru"
        assert service.mask_dilation == 8
        assert service.use_gpu is False
    
    @patch('src.services.cleaner_service.ProPainterModelAdapter')
    def test_process_success(self, mock_adapter, mock_dependencies, tmp_path):
        """Test successful processing."""
        # Mock adapter
        adapter_instance = Mock()
        adapter_instance.process_chunk.return_value = Mock()
        mock_adapter.return_value = adapter_instance
        
        service = SubtitleRemoverService()
        service.model_adapter = adapter_instance
        service.model_loaded = True
        
        # Create request
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        
        request = InpaintingRequest(
            input_dir=input_dir,
            output_dir=output_dir
        )
        
        # Process
        result = service.process(request)
        
        assert result.success is True
        assert result.frames_processed == 10
        assert result.output_path == output_dir
    
    def test_process_failure(self, mock_dependencies, tmp_path):
        """Test processing failure."""
        # Make video reading fail
        mock_dependencies['read_video'].side_effect = Exception("Read failed")
        
        service = SubtitleRemoverService()
        
        # Create request
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        
        request = InpaintingRequest(
            input_dir=input_dir,
            output_dir=output_dir
        )
        
        # Process
        result = service.process(request)
        
        assert result.success is False
        assert len(result.errors) > 0


class TestWrapper:
    """Test wrapper for backward compatibility."""
    
    @pytest.fixture
    def mock_service(self):
        """Mock SubtitleRemoverService."""
        with patch('src.services.wrapper.SubtitleRemoverService') as mock:
            instance = Mock()
            instance.process_frames_direct.return_value = ProcessingResult(
                success=True,
                output_path=Path("/tmp/output"),
                frames_processed=10,
                errors=[]
            )
            instance.is_available.return_value = True
            mock.return_value = instance
            yield mock
    
    def test_wrapper_init(self, mock_service):
        """Test wrapper initialization."""
        wrapper = SubtitleRemoverProPainterWrapper(
            lang="ru",
            mask_dilation=8
        )
        
        assert wrapper._lang == "ru"
        assert wrapper._mask_dilation == 8
    
    def test_wrapper_process(self, mock_service, tmp_path):
        """Test wrapper process method."""
        wrapper = SubtitleRemoverProPainterWrapper()
        
        # Create test frames
        frame_paths = [tmp_path / f"frame{i}.png" for i in range(3)]
        for path in frame_paths:
            path.write_bytes(b"dummy")
        
        output_dir = tmp_path / "output"
        
        # Process
        result = wrapper.process(frame_paths, output_dir)
        
        assert result.success is True
        assert result.frames_processed == 10
        mock_service.return_value.process_frames_direct.assert_called_once()
    
    def test_wrapper_is_available(self, mock_service):
        """Test wrapper availability check."""
        # Mock imports
        with patch('src.services.wrapper.cv2', create=True), \
             patch('src.services.wrapper.torch', create=True), \
             patch('src.services.wrapper.np', create=True), \
             patch('src.services.wrapper.PaddleOCR', create=True):
            
            available = SubtitleRemoverProPainterWrapper.is_available()
            assert available is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
