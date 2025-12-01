"""
Unit tests for native Python processors.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch


class TestGPUMemoryDetector:
    """Test GPU memory detection."""

    def test_suggest_batch_size_low_vram(self):
        """Test batch size suggestion for low VRAM."""
        from infrastructure.processors.realesrgan.native import GPUMemoryDetector

        # <12GB -> batch 1
        assert GPUMemoryDetector.suggest_batch_size(8 * 1024) == 1

    def test_suggest_batch_size_medium_vram(self):
        """Test batch size suggestion for medium VRAM."""
        from infrastructure.processors.realesrgan.native import GPUMemoryDetector

        # 12-16GB -> batch 2
        assert GPUMemoryDetector.suggest_batch_size(14 * 1024) == 2

        # 16-24GB -> batch 4
        assert GPUMemoryDetector.suggest_batch_size(20 * 1024) == 4

    def test_suggest_batch_size_high_vram(self):
        """Test batch size suggestion for high VRAM."""
        from infrastructure.processors.realesrgan.native import GPUMemoryDetector

        # 24-32GB -> batch 8
        assert GPUMemoryDetector.suggest_batch_size(28 * 1024) == 8

        # >=32GB -> batch 16
        assert GPUMemoryDetector.suggest_batch_size(40 * 1024) == 16


class TestRealESRGANNative:
    """Test Real-ESRGAN native implementation."""

    def test_initialization(self):
        """Test processor initialization."""
        from infrastructure.processors.realesrgan.native import RealESRGANNative

        processor = RealESRGANNative(
            scale=2,
            tile_size=512,
            batch_size=4
        )

        assert processor.scale == 2
        assert processor.tile_size == 512
        assert processor.batch_size == 4
        assert processor.half is True  # default

    def test_batch_size_auto_detection(self):
        """Test auto batch size detection."""
        from infrastructure.processors.realesrgan.native import RealESRGANNative

        # Should auto-detect
        processor = RealESRGANNative(batch_size=None)

        assert processor.batch_size >= 1
        assert processor.batch_size <= 16


class TestRIFENative:
    """Test RIFE native implementation."""

    def test_initialization(self):
        """Test processor initialization."""
        # May raise FileNotFoundError if model not present
        try:
            from infrastructure.processors.rife.native import RIFENative

            processor = RIFENative(factor=2.0)

            assert processor.factor == 2.0
            assert processor.scale == 1.0
        except FileNotFoundError:
            pytest.skip("RIFE model not found")

    def test_mids_calculation(self):
        """Test intermediate frames calculation."""
        try:
            from infrastructure.processors.rife.native import RIFENative

            processor = RIFENative(factor=2.0)
            mids = processor._calculate_mids_per_pair()
            assert mids == 1  # factor 2 -> 1 mid

            processor.factor = 4.0
            mids = processor._calculate_mids_per_pair()
            assert mids == 3  # factor 4 -> 3 mids
        except FileNotFoundError:
            pytest.skip("RIFE model not found")


class TestNativeWrappers:
    """Test wrapper adapters for native processors."""

    def test_realesrgan_native_wrapper(self):
        """Test Real-ESRGAN native wrapper."""
        try:
            from infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper

            # Should not raise if dependencies available
            if RealESRGANNativeWrapper.is_available():
                wrapper = RealESRGANNativeWrapper()
                assert wrapper.supports_gpu() is True
            else:
                pytest.skip("Real-ESRGAN dependencies not available")
        except ImportError:
            pytest.skip("Native wrapper not available")

    def test_rife_native_wrapper(self):
        """Test RIFE native wrapper."""
        try:
            from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper

            # Should not raise if dependencies available
            if RIFENativeWrapper.is_available():
                wrapper = RIFENativeWrapper()
                assert wrapper.supports_gpu() is True
            else:
                pytest.skip("RIFE dependencies not available")
        except ImportError:
            pytest.skip("Native wrapper not available")


class TestFactoryNativeSupport:
    """Test factory support for native processors."""

    def test_factory_with_native_flag(self):
        """Test factory with use_native=True."""
        from application.factories import ProcessorFactory

        factory = ProcessorFactory(use_native=True)
        assert factory.use_native is True

    def test_factory_env_variable(self, monkeypatch):
        """Test factory reads USE_NATIVE_PROCESSORS env."""
        from application.factories import ProcessorFactory

        monkeypatch.setenv('USE_NATIVE_PROCESSORS', '1')
        factory = ProcessorFactory()
        assert factory.use_native is True

    def test_create_native_upscaler(self):
        """Test creating native upscaler."""
        from application.factories import ProcessorFactory

        factory = ProcessorFactory(use_native=True)

        try:
            upscaler = factory.create_upscaler(prefer='native')
            assert upscaler is not None
        except Exception:
            pytest.skip("Native upscaler not available")

    def test_create_native_interpolator(self):
        """Test creating native interpolator."""
        from application.factories import ProcessorFactory

        factory = ProcessorFactory(use_native=True)

        try:
            interpolator = factory.create_interpolator(prefer='native')
            assert interpolator is not None
        except Exception:
            pytest.skip("Native interpolator not available")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

