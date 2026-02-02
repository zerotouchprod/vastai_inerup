"""
Unit tests for image loader utilities.
"""

import pytest
import base64
from io import BytesIO
from unittest.mock import Mock, patch, MagicMock
from PIL import Image

from src.services.generation.utils.image_loader import ImageLoader, load_image


@pytest.fixture
def loader():
    """Create ImageLoader instance."""
    return ImageLoader(max_size_mb=10)


@pytest.fixture
def sample_image():
    """Create sample RGB image."""
    img = Image.new('RGB', (512, 512), color=(255, 0, 0))
    return img


@pytest.fixture
def sample_image_bytes(sample_image):
    """Convert sample image to bytes."""
    buffer = BytesIO()
    sample_image.save(buffer, format='JPEG')
    return buffer.getvalue()


class TestImageLoaderURL:
    """Tests for URL loading."""

    def test_load_from_url_success(self, loader, sample_image_bytes):
        """Test successful URL loading."""
        with patch('requests.get') as mock_get:
            # Mock response
            mock_response = Mock()
            mock_response.content = sample_image_bytes
            mock_response.headers = {'Content-Length': str(len(sample_image_bytes))}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            # Load
            result = loader.load("https://example.com/image.jpg")

            # Assertions
            assert isinstance(result, Image.Image)
            assert result.mode == 'RGB'
            assert result.size == (512, 512)
            mock_get.assert_called_once()

    def test_load_from_url_too_large(self, loader):
        """Test rejection of oversized images."""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            # 20MB content-length
            mock_response.headers = {'Content-Length': str(20 * 1024 * 1024)}
            mock_get.return_value = mock_response

            with pytest.raises(ValueError, match="too large"):
                loader.load("https://example.com/huge.jpg")

    def test_load_from_url_network_error(self, loader):
        """Test handling of network errors."""
        with patch('requests.get', side_effect=Exception("Network error")):
            with pytest.raises(IOError, match="Network error"):
                loader.load("https://example.com/image.jpg")


class TestImageLoaderBase64:
    """Tests for base64 loading."""

    def test_load_from_base64_success(self, loader, sample_image_bytes):
        """Test successful base64 loading."""
        # Create base64 data URI
        encoded = base64.b64encode(sample_image_bytes).decode()
        data_uri = f"data:image/jpeg;base64,{encoded}"

        # Load
        result = loader.load(data_uri)

        # Assertions
        assert isinstance(result, Image.Image)
        assert result.mode == 'RGB'
        assert result.size == (512, 512)

    def test_load_from_base64_invalid_format(self, loader):
        """Test rejection of invalid data URI format."""
        with pytest.raises(ValueError, match="Invalid data URI"):
            loader.load("data:text/plain;base64,SGVsbG8=")

    def test_load_from_base64_missing_comma(self, loader):
        """Test rejection of malformed data URI."""
        with pytest.raises(ValueError, match="missing comma"):
            loader.load("data:image/jpeg;base64SGVsbG8=")

    def test_load_from_base64_invalid_encoding(self, loader):
        """Test handling of invalid base64."""
        with pytest.raises(ValueError, match="Invalid base64"):
            loader.load("data:image/jpeg;base64,INVALID!!!BASE64")

    def test_load_from_base64_too_large(self, loader):
        """Test size limit enforcement for base64."""
        # Create 15MB image (exceeds 10MB limit)
        large_data = b'x' * (15 * 1024 * 1024)
        encoded = base64.b64encode(large_data).decode()
        data_uri = f"data:image/jpeg;base64,{encoded}"

        with pytest.raises(ValueError, match="too large"):
            loader.load(data_uri)


class TestImageLoaderFile:
    """Tests for local file loading."""

    def test_load_from_file_success(self, loader, tmp_path, sample_image):
        """Test successful file loading."""
        # Save to temp file
        file_path = tmp_path / "test.jpg"
        sample_image.save(file_path)

        # Load
        result = loader.load(str(file_path))

        # Assertions
        assert isinstance(result, Image.Image)
        assert result.mode == 'RGB'
        assert result.size == (512, 512)

    def test_load_from_file_not_found(self, loader):
        """Test handling of missing file."""
        with pytest.raises(FileNotFoundError, match="not found"):
            loader.load("/nonexistent/path/image.jpg")

    def test_load_from_file_not_a_file(self, loader, tmp_path):
        """Test rejection of directory path."""
        dir_path = tmp_path / "directory"
        dir_path.mkdir()

        with pytest.raises(ValueError, match="not a file"):
            loader.load(str(dir_path))

    def test_load_from_file_too_large(self, loader, tmp_path):
        """Test file size limit enforcement."""
        # Create 15MB file
        file_path = tmp_path / "large.dat"
        file_path.write_bytes(b'x' * (15 * 1024 * 1024))

        with pytest.raises(ValueError, match="too large"):
            loader.load(str(file_path))


class TestImageValidation:
    """Tests for image validation and conversion."""

    def test_convert_rgba_to_rgb(self, loader, tmp_path):
        """Test conversion of RGBA to RGB."""
        # Create RGBA image
        img = Image.new('RGBA', (512, 512), color=(255, 0, 0, 128))
        file_path = tmp_path / "rgba.png"
        img.save(file_path)

        # Load
        result = loader.load(str(file_path))

        # Should be converted to RGB
        assert result.mode == 'RGB'

    def test_convert_grayscale_to_rgb(self, loader, tmp_path):
        """Test conversion of grayscale to RGB."""
        # Create grayscale image
        img = Image.new('L', (512, 512), color=128)
        file_path = tmp_path / "gray.jpg"
        img.save(file_path)

        # Load
        result = loader.load(str(file_path))

        # Should be converted to RGB
        assert result.mode == 'RGB'

    def test_supported_formats(self, loader, tmp_path, sample_image):
        """Test all supported formats."""
        formats = [
            ('jpeg', 'JPEG'),
            ('png', 'PNG'),
            ('webp', 'WEBP')
        ]

        for ext, fmt in formats:
            file_path = tmp_path / f"test.{ext}"
            sample_image.save(file_path, format=fmt)

            result = loader.load(str(file_path))
            assert isinstance(result, Image.Image)
            assert result.mode == 'RGB'


class TestConvenienceFunction:
    """Tests for convenience function."""

    def test_load_image_function(self, tmp_path, sample_image):
        """Test load_image convenience function."""
        file_path = tmp_path / "test.jpg"
        sample_image.save(file_path)

        result = load_image(str(file_path))

        assert isinstance(result, Image.Image)
        assert result.mode == 'RGB'

    def test_load_image_custom_size_limit(self, tmp_path):
        """Test custom size limit."""
        # Create 2MB file
        file_path = tmp_path / "medium.dat"
        file_path.write_bytes(b'x' * (2 * 1024 * 1024))

        # Should fail with 1MB limit
        with pytest.raises(ValueError, match="too large"):
            load_image(str(file_path), max_size_mb=1)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_empty_source(self, loader):
        """Test rejection of empty source."""
        with pytest.raises(ValueError, match="non-empty string"):
            loader.load("")

    def test_none_source(self, loader):
        """Test rejection of None source."""
        with pytest.raises(ValueError, match="non-empty string"):
            loader.load(None)

    def test_invalid_image_data(self, loader):
        """Test handling of corrupt image data."""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.content = b'NOT AN IMAGE'
            mock_response.headers = {'Content-Length': '13'}
            mock_response.raise_for_status = Mock()
            mock_get.return_value = mock_response

            with pytest.raises(IOError):
                loader.load("https://example.com/corrupt.jpg")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
