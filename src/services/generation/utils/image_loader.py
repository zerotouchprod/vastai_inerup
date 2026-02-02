"""
Image loading utilities for Image-to-Video generation.

Supports:
- HTTP(S) URLs
- Base64 data URIs
- Local file paths
"""

declare(strict_types=1);

import base64
import io
from pathlib import Path
from typing import Union, Optional
from urllib.parse import urlparse

import requests
from PIL import Image

from src.shared.logging import get_logger


logger = get_logger(__name__)


class ImageLoader:
    """
    Utility class for loading images from various sources.

    Supports:
    - HTTP(S) URLs (e.g., https://example.com/image.jpg)
    - Base64 data URIs (e.g., data:image/jpeg;base64,...)
    - Local file paths (e.g., /path/to/image.jpg)

    Features:
    - Format validation (JPEG, PNG, WebP)
    - Size limits enforcement
    - Automatic RGB conversion
    - Error handling with detailed messages
    """

    SUPPORTED_FORMATS = {'JPEG', 'PNG', 'WEBP'}
    DEFAULT_MAX_SIZE_MB = 10

    def __init__(
        self,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        timeout_seconds: int = 30
    ):
        """
        Initialize image loader.

        Args:
            max_size_mb: Maximum allowed image size in megabytes
            timeout_seconds: HTTP request timeout
        """
        self.max_size_mb = max_size_mb
        self.timeout_seconds = timeout_seconds

    def load(self, source: str) -> Image.Image:
        """
        Load image from any supported source.

        Args:
            source: Image source (URL, base64 data URI, or file path)

        Returns:
            PIL Image object in RGB mode

        Raises:
            ValueError: If source format is invalid or unsupported
            FileNotFoundError: If local file doesn't exist
            IOError: If loading fails

        Example:
            loader = ImageLoader()

            # From URL
            img = loader.load("https://example.com/image.jpg")

            # From base64
            img = loader.load("data:image/jpeg;base64,/9j/4AAQ...")

            # From file
            img = loader.load("/path/to/image.jpg")
        """
        if not source or not isinstance(source, str):
            raise ValueError("Source must be a non-empty string")

        # Determine source type and load
        if source.startswith(('http://', 'https://')):
            return self._load_from_url(source)
        elif source.startswith('data:image'):
            return self._load_from_base64(source)
        else:
            return self._load_from_file(source)

    def _load_from_url(self, url: str) -> Image.Image:
        """
        Load image from HTTP(S) URL.

        Args:
            url: HTTP(S) URL to image

        Returns:
            PIL Image object

        Raises:
            ValueError: If image too large or invalid format
            IOError: If download fails
        """
        logger.info(f"Loading image from URL: {url[:100]}...")

        try:
            # Download with streaming to check size before loading
            response = requests.get(
                url,
                timeout=self.timeout_seconds,
                stream=True,
                headers={'User-Agent': 'video-gen-worker/1.0'}
            )
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get('Content-Length')
            if content_length:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > self.max_size_mb:
                    raise ValueError(
                        f"Image too large: {size_mb:.1f}MB exceeds limit of {self.max_size_mb}MB"
                    )

            # Load image from bytes
            image_bytes = response.content
            image = Image.open(io.BytesIO(image_bytes))

            logger.info(f"✓ Image loaded from URL: {image.size} {image.format}")
            return self._validate_and_convert(image)

        except requests.RequestException as e:
            raise IOError(f"Failed to download image from {url}: {e}")
        except Exception as e:
            raise IOError(f"Failed to load image from URL: {e}")

    def _load_from_base64(self, data_uri: str) -> Image.Image:
        """
        Load image from base64 data URI.

        Args:
            data_uri: Data URI (e.g., data:image/jpeg;base64,...)

        Returns:
            PIL Image object

        Raises:
            ValueError: If data URI format is invalid
        """
        logger.info("Loading image from base64 data URI...")

        try:
            # Parse data URI: data:image/jpeg;base64,<encoded_data>
            if ',' not in data_uri:
                raise ValueError("Invalid data URI format: missing comma separator")

            header, encoded = data_uri.split(',', 1)

            # Validate header
            if not header.startswith('data:image'):
                raise ValueError(f"Invalid data URI: expected 'data:image', got '{header[:20]}...'")

            # Decode base64
            try:
                decoded = base64.b64decode(encoded)
            except Exception as e:
                raise ValueError(f"Invalid base64 encoding: {e}")

            # Check size
            size_mb = len(decoded) / (1024 * 1024)
            if size_mb > self.max_size_mb:
                raise ValueError(
                    f"Image too large: {size_mb:.1f}MB exceeds limit of {self.max_size_mb}MB"
                )

            # Load image
            image = Image.open(io.BytesIO(decoded))

            logger.info(f"✓ Image loaded from base64: {image.size} {image.format}")
            return self._validate_and_convert(image)

        except Exception as e:
            raise ValueError(f"Failed to load image from base64: {e}")

    def _load_from_file(self, path: str) -> Image.Image:
        """
        Load image from local file system.

        Args:
            path: Path to image file

        Returns:
            PIL Image object

        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read
        """
        file_path = Path(path)

        logger.info(f"Loading image from file: {file_path}")

        if not file_path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")

        if not file_path.is_file():
            raise ValueError(f"Path is not a file: {path}")

        # Check file size
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.max_size_mb:
            raise ValueError(
                f"Image file too large: {size_mb:.1f}MB exceeds limit of {self.max_size_mb}MB"
            )

        try:
            image = Image.open(file_path)
            logger.info(f"✓ Image loaded from file: {image.size} {image.format}")
            return self._validate_and_convert(image)
        except Exception as e:
            raise IOError(f"Failed to load image from file: {e}")

    def _validate_and_convert(self, image: Image.Image) -> Image.Image:
        """
        Validate image format and convert to RGB.

        Args:
            image: PIL Image object

        Returns:
            PIL Image object in RGB mode

        Raises:
            ValueError: If format is unsupported
        """
        # Validate format
        if image.format and image.format not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported image format: {image.format}. "
                f"Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        # Convert to RGB (required for CogVideoX)
        if image.mode != 'RGB':
            logger.debug(f"Converting image from {image.mode} to RGB")
            image = image.convert('RGB')

        return image


def load_image(source: str, max_size_mb: int = 10) -> Image.Image:
    """
    Convenience function to load image from any source.

    Args:
        source: Image source (URL, base64 data URI, or file path)
        max_size_mb: Maximum allowed image size in megabytes

    Returns:
        PIL Image object in RGB mode

    Raises:
        ValueError: If source format is invalid or unsupported
        FileNotFoundError: If local file doesn't exist
        IOError: If loading fails
    """
    loader = ImageLoader(max_size_mb=max_size_mb)
    return loader.load(source)
