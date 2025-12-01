"""HTTP/S3 downloader implementation."""

import requests
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from domain.protocols import IDownloader
from domain.exceptions import DownloadError
from shared.logging import get_logger
from shared.retry import retry_with_backoff

logger = get_logger(__name__)


class HttpDownloader:
    """
    Downloads files over HTTP/HTTPS.
    Implements IDownloader protocol.
    """

    def __init__(self, timeout: int = 600, chunk_size: int = 8192):
        """
        Initialize HTTP downloader.

        Args:
            timeout: Request timeout in seconds
            chunk_size: Download chunk size in bytes
        """
        self.timeout = timeout
        self.chunk_size = chunk_size
        self._logger = get_logger(__name__)

    def supports(self, url: str) -> bool:
        """Check if URL is supported (http/https)."""
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https')

    @retry_with_backoff(max_attempts=3, backoff_seconds=2)
    def download(self, url: str, destination: Path) -> Path:
        """
        Download file from URL to destination.

        Args:
            url: URL to download from
            destination: Destination file path

        Returns:
            Path to downloaded file

        Raises:
            DownloadError: If download fails
        """
        if not self.supports(url):
            raise DownloadError(f"Unsupported URL scheme: {url}")

        self._logger.info(f"Downloading {url} to {destination}")

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)

            response = requests.get(url, stream=True, timeout=self.timeout)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(destination, 'wb') as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if downloaded % (10 * 1024 * 1024) == 0:  # Log every 10MB
                                self._logger.debug(
                                    f"Download progress: {progress:.1f}%"
                                )

            self._logger.info(
                f"Downloaded {downloaded} bytes to {destination}"
            )
            return destination

        except requests.RequestException as e:
            raise DownloadError(f"Failed to download {url}: {e}") from e
        except Exception as e:
            raise DownloadError(f"Unexpected error downloading {url}: {e}") from e

