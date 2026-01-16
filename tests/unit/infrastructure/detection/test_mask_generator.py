"""
Unit tests for MaskGenerator component.
Tests geometry, ROI constraints, and mask generation logic.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

from src.infrastructure.detection.components.mask_generator import MaskGenerator


class MockConfig:
    """Mock configuration for testing."""
    def __init__(self):
        self.ROI = "bottom"
        self.MASK_DILATION = 2
        self.MASK_BLUR = 1
        self.USE_MSER = True
        self.USE_GRADIENT = True
        self.MSER_DELTA = 5
        self.MSER_MIN_AREA = 30
        self.MSER_MAX_AREA = 1000
        self.GRADIENT_THRESHOLD = 0.3


@pytest.fixture
def mock_config():
    """Fixture providing mock configuration."""
    return MockConfig()


@pytest.fixture
def sample_image():
    """Fixture providing a sample test image."""
    return np.zeros((100, 100, 3), dtype=np.uint8)


@pytest.fixture
def mock_ocr_results():
    """Fixture providing mock OCR results."""
    return [
        (np.array([[10, 10], [20, 10], [20, 20], [10, 20]], dtype=np.float32), 0.9),
        (np.array([[50, 50], [60, 50], [60, 60], [50, 60]], dtype=np.float32), 0.8)
    ]


class TestMaskGenerator:
    """Test suite for MaskGenerator."""
    
    def test_initialization(self, mock_config):
        """Test that MaskGenerator initializes correctly."""
        generator = MaskGenerator(mock_config)
        
        assert generator.config == mock_config
        assert generator.roi_str == "bottom"
        assert generator.mask_dilation == 2
        assert generator.mask_blur == 1
        assert generator.use_mser == True
        assert generator.use_gradient == True
    
    def test_generate_mask_basic(self, mock_config, sample_image, mock_ocr_results):
        """Test basic mask generation from OCR results."""
        generator = MaskGenerator(mock_config)
        
        # Mock internal methods to isolate test
        with patch.object(generator, '_apply_roi_constraint') as mock_roi:
            with patch.object(generator, '_dilate_and_blur_mask') as mock_dilate:
                mock_roi.return_value = np.ones((100, 100), dtype=np.uint8) * 255
                mock_dilate.side_effect = lambda x: x
                
                mask = generator.generate_mask(sample_image, mock_ocr_results, "bottom")
                
                # Verify mask shape
                assert mask.shape == (100, 100)
                assert mask.dtype == np.uint8
                
                # Verify ROI constraint was applied
                mock_roi.assert_called_once()
                
                # Verify dilation was applied
                mock_dilate.assert_called_once()
    
    def test_generate_mask_empty_ocr(self, mock_config, sample_image):
        """Test mask generation with empty OCR results."""
        generator = MaskGenerator(mock_config)
        
        mask = generator.generate_mask(sample_image, [], "bottom")
        
        # Should return empty mask
        assert mask.shape == (100, 100)
        assert mask.dtype == np.uint8
        assert np.all(mask == 0)
    
    def test_generate_mask_none_ocr(self, mock_config, sample_image):
        """Test mask generation with None OCR results."""
        generator = MaskGenerator(mock_config)
        
        mask = generator.generate_mask(sample_image, None, "bottom")
        
        # Should return empty mask
        assert mask.shape == (100, 100)
        assert mask.dtype == np.uint8
        assert np.all(mask == 0)
    
    def test_apply_roi_constraint_bottom(self, mock_config):
        """Test ROI constraint with 'bottom' region."""
        generator = MaskGenerator(mock_config)
        
        # Create a mask that covers entire image
        full_mask = np.ones((100, 100), dtype=np.uint8) * 255
        
        # Apply bottom ROI (assume bottom 30%)
        constrained_mask = generator._apply_roi_constraint(full_mask, "bottom")
        
        # Verify top part is zero
        assert np.all(constrained_mask[0:70, :] == 0)
        
        # Verify bottom part is preserved (non-zero)
        assert np.any(constrained_mask[70:, :] == 255)
    
    def test_apply_roi_constraint_top(self, mock_config):
        """Test ROI constraint with 'top' region."""
        generator = MaskGenerator(mock_config)
        
        full_mask = np.ones((100, 100), dtype=np.uint8) * 255
        constrained_mask = generator._apply_roi_constraint(full_mask, "top")
        
        # Verify bottom part is zero
        assert np.all(constrained_mask[30:, :] == 0)
        
        # Verify top part is preserved
        assert np.any(constrained_mask[:30, :] == 255)
    
    def test_apply_roi_constraint_custom_coords(self, mock_config):
        """Test ROI constraint with custom coordinates."""
        generator = MaskGenerator(mock_config)
        
        full_mask = np.ones((100, 100), dtype=np.uint8) * 255
        roi_str = "10,20,80,90"  # x1,y1,x2,y2
        
        constrained_mask = generator._apply_roi_constraint(full_mask, roi_str)
        
        # Verify area outside ROI is zero
        assert np.all(constrained_mask[0:20, :] == 0)  # Above y1
        assert np.all(constrained_mask[90:, :] == 0)   # Below y2
        assert np.all(constrained_mask[:, 0:10] == 0)  # Left of x1
        assert np.all(constrained_mask[:, 80:] == 0)   # Right of x2
        
        # Verify area inside ROI is preserved
        assert np.any(constrained_mask[20:90, 10:80] == 255)
    
    def test_apply_roi_constraint_none(self, mock_config):
        """Test ROI constraint with None/empty ROI."""
        generator = MaskGenerator(mock_config)
        
        full_mask = np.ones((100, 100), dtype=np.uint8) * 255
        
        # Test with None
        mask1 = generator._apply_roi_constraint(full_mask, None)
        assert np.all(mask1 == 255)
        
        # Test with empty string
        mask2 = generator._apply_roi_constraint(full_mask, "")
        assert np.all(mask2 == 255)
        
        # Test with "none"
        mask3 = generator._apply_roi_constraint(full_mask, "none")
        assert np.all(mask3 == 255)
    
    def test_dilate_and_blur_mask(self, mock_config):
        """Test mask dilation and blurring."""
        generator = MaskGenerator(mock_config)
        
        # Create a small mask with a single white pixel
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[5, 5] = 255
        
        # Apply dilation and blur
        result = generator._dilate_and_blur_mask(mask)
        
        # Verify shape preserved
        assert result.shape == (10, 10)
        assert result.dtype == np.uint8
        
        # With dilation=2, the single pixel should expand
        # We can't predict exact expansion due to kernel, but should have more white pixels
        white_pixels_original = np.sum(mask == 255)
        white_pixels_result = np.sum(result == 255)
        assert white_pixels_result >= white_pixels_original
    
    def test_dilate_and_blur_mask_zero_dilation(self, mock_config):
        """Test mask processing with zero dilation."""
        config = MockConfig()
        config.MASK_DILATION = 0
        config.MASK_BLUR = 0
        
        generator = MaskGenerator(config)
        
        mask = np.ones((10, 10), dtype=np.uint8) * 255
        result = generator._dilate_and_blur_mask(mask)
        
        # Should be unchanged (or nearly unchanged due to blur kernel)
        assert np.array_equal(result, mask) or np.allclose(result, mask)
    
    def test_preprocess_for_ocr(self, mock_config, sample_image):
        """Test image preprocessing for OCR."""
        generator = MaskGenerator(mock_config)
        
        # Create an image with varying intensity
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        
        preprocessed = generator.preprocess_for_ocr(image)
        
        # Verify shape preserved
        assert preprocessed.shape == image.shape
        assert preprocessed.dtype == np.uint8
        
        # Should be different from original (due to processing)
        assert not np.array_equal(preprocessed, image)
    
    def test_preprocess_for_ocr_gray(self, mock_config):
        """Test OCR preprocessing with grayscale image."""
        generator = MaskGenerator(mock_config)
        
        gray_image = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
        
        # Should convert to BGR
        preprocessed = generator.preprocess_for_ocr(gray_image)
        
        assert preprocessed.shape == (100, 100, 3)
        assert preprocessed.dtype == np.uint8
    
    def test_generate_hybrid_mask_mser_only(self, mock_config):
        """Test hybrid mask generation with MSER only."""
        config = MockConfig()
        config.USE_MSER = True
        config.USE_GRADIENT = False
        
        generator = MaskGenerator(config)
        
        # Mock cv2.MSER_create and detect
        with patch('src.infrastructure.detection.components.mask_generator.cv2.MSER_create') as mock_mser_create:
            mock_mser = Mock()
            mock_mser_create.return_value = mock_mser
            mock_mser.detectRegions.return_value = ([np.array([[5, 5], [6, 5], [6, 6], [5, 6]])], [])
            
            image = np.zeros((10, 10), dtype=np.uint8)
            mask = generator._generate_hybrid_mask(image)
            
            # Verify MSER was called
            mock_mser_create.assert_called_once()
            mock_mser.detectRegions.assert_called_once()
            
            # Verify mask shape
            assert mask.shape == (10, 10)
            assert mask.dtype == np.uint8
    
    def test_generate_hybrid_mask_gradient_only(self, mock_config):
        """Test hybrid mask generation with gradient only."""
        config = MockConfig()
        config.USE_MSER = False
        config.USE_GRADIENT = True
        
        generator = MaskGenerator(config)
        
        # Mock cv2.Sobel and thresholding
        with patch('src.infrastructure.detection.components.mask_generator.cv2.Sobel') as mock_sobel:
            mock_sobel.return_value = np.zeros((10, 10), dtype=np.float32)
            
            image = np.zeros((10, 10), dtype=np.uint8)
            mask = generator._generate_hybrid_mask(image)
            
            # Verify Sobel was called
            mock_sobel.assert_called()
            
            # Verify mask shape
            assert mask.shape == (10, 10)
            assert mask.dtype == np.uint8
    
    def test_generate_hybrid_mask_neither(self, mock_config):
        """Test hybrid mask generation with both MSER and gradient disabled."""
        config = MockConfig()
        config.USE_MSER = False
        config.USE_GRADIENT = False
        
        generator = MaskGenerator(config)
        
        image = np.zeros((10, 10), dtype=np.uint8)
        mask = generator._generate_hybrid_mask(image)
        
        # Should return empty mask
        assert mask.shape == (10, 10)
        assert mask.dtype == np.uint8
        assert np.all(mask == 0)
    
    def test_combine_masks(self, mock_config):
        """Test mask combination logic."""
        generator = MaskGenerator(mock_config)
        
        # Create test masks
        mask1 = np.array([[0, 255], [0, 0]], dtype=np.uint8)
        mask2 = np.array([[255, 0], [0, 0]], dtype=np.uint8)
        mask3 = np.array([[0, 0], [255, 0]], dtype=np.uint8)
        
        combined = generator._combine_masks([mask1, mask2, mask3])
        
        # Should be union of all masks
        expected = np.array([[255, 255], [255, 0]], dtype=np.uint8)
        assert np.array_equal(combined, expected)
    
    def test_combine_masks_empty(self, mock_config):
        """Test mask combination with empty list."""
        generator = MaskGenerator(mock_config)
        
        combined = generator._combine_masks([])
        
        # Should return zeros
        assert combined is None or np.all(combined == 0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
