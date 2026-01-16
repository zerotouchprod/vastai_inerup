"""
Unit tests for ResolutionCalculator component.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from src.core.config import AppConfig
from src.infrastructure.inpainting.components.resolution import ResolutionCalculator


class TestResolutionCalculator:
    """Test suite for ResolutionCalculator."""
    
    @pytest.fixture
    def config(self):
        """Create a mock AppConfig."""
        config = Mock(spec=AppConfig)
        config.AUTO_DOWNSCALE = True
        config.MAX_HEIGHT = 1080
        config.MAX_FRAMES_PER_CHUNK = 4
        config.PROPAINTER_OVERLAP = 2
        return config
    
    @pytest.fixture
    def calculator(self, config):
        """Create ResolutionCalculator instance."""
        return ResolutionCalculator(config)
    
    def test_ensure_divisible_by_32_basic(self, calculator):
        """Test that dimensions are made divisible by 32."""
        # Test exact multiples
        assert calculator.ensure_divisible_by_32(1920, 1088) == (1920, 1088)  # 1088 divisible by 32
        
        # Test non-multiples: 1921 -> 1920, 1081 -> 1056 (1081 // 32 = 33, 33*32=1056)
        assert calculator.ensure_divisible_by_32(1921, 1081) == (1920, 1056)
        
        # Test small dimensions (minimum 32)
        assert calculator.ensure_divisible_by_32(10, 20) == (32, 32)
        
        # Test edge cases
        assert calculator.ensure_divisible_by_32(33, 65) == (32, 64)
        
        # Test 1080 -> 1056 (round down)
        assert calculator.ensure_divisible_by_32(1920, 1080) == (1920, 1056)
    
    def test_should_downscale_when_auto_downscale_false(self, calculator):
        """Test that downscaling is disabled when AUTO_DOWNSCALE is False."""
        calculator.config.AUTO_DOWNSCALE = False
        
        # Even if height exceeds MAX_HEIGHT, should return False
        assert calculator.should_downscale(2000) == False
    
    def test_should_downscale_when_auto_downscale_true(self, calculator):
        """Test that downscaling logic respects MAX_HEIGHT."""
        calculator.config.AUTO_DOWNSCALE = True
        
        # Height exceeds MAX_HEIGHT (1080)
        assert calculator.should_downscale(2000) == True
        
        # Height equals MAX_HEIGHT
        assert calculator.should_downscale(1080) == False
        
        # Height less than MAX_HEIGHT
        assert calculator.should_downscale(720) == False
    
    @pytest.mark.parametrize("width,height,expected_width,expected_height", [
        # Landscape videos (width >= height)
        (1920, 1080, 1920, 1056),  # 1080 -> 1056 (1080 // 32 = 33, 33*32=1056)
        (1936, 1088, 1920, 1088),  # 1936 -> 1920 (1936 // 32 = 60), 1088 already divisible
        (1910, 1070, 1888, 1056),  # Needs adjustment
        # Portrait videos (height > width)
        (1080, 1920, 1056, 1920),  # 1080 -> 1056, 1920 divisible by 32
        (1070, 1910, 1056, 1888),  # Both need adjustment
    ])
    def test_ensure_divisible_by_32_parametrized(self, calculator, width, height, 
                                                expected_width, expected_height):
        """Test divisible by 32 logic with various inputs."""
        result_width, result_height = calculator.ensure_divisible_by_32(width, height)
        assert result_width == expected_width
        assert result_height == expected_height
        assert result_width % 32 == 0
        assert result_height % 32 == 0
    
    def test_calculate_target_dimensions_no_downscale(self, calculator):
        """Test calculate_target_dimensions when AUTO_DOWNSCALE is False."""
        calculator.config.AUTO_DOWNSCALE = False
        # Should return original dimensions (made divisible by 32)
        width, height = calculator.calculate_target_dimensions(1920, 1080)
        assert width == 1920  # 1920 divisible by 32
        assert height == 1056  # 1080 -> 1056
    
    def test_calculate_target_dimensions_with_downscale(self, calculator):
        """Test calculate_target_dimensions when AUTO_DOWNSCALE is True."""
        calculator.config.AUTO_DOWNSCALE = True
        calculator.config.MAX_HEIGHT = 720
        
        # Original 1920x1080 > MAX_HEIGHT 720, should downscale
        width, height = calculator.calculate_target_dimensions(1920, 1080)
        # Should scale to max dimension 720, preserve aspect ratio
        # 1920/1080 = 1.777, target height = 720, width = 720 * 1.777 = 1280
        # Then make divisible by 32: 1280 divisible, 720 -> 704 (720 // 32 = 22, 22*32=704)
        assert width == 1280
        assert height == 704
    
    def test_calculate_target_dimensions_with_vram(self, calculator):
        """Test calculate_target_dimensions with GPU VRAM consideration."""
        calculator.config.AUTO_DOWNSCALE = True
        calculator.config.MAX_HEIGHT = 1080
        
        # With 24GB VRAM (RTX 3090), max_height should be 2160 (4K height)
        width, height = calculator.calculate_target_dimensions(4096, 2160, gpu_vram_gb=24.0)
        # VRAM fits 4 frames at native, but MAX_HEIGHT constraint (1080) forces downscale
        # Downscaled to 2048x1056 (preserving aspect ratio, divisible by 32)
        assert width == 2048
        assert height == 1056
