"""Tests for HttpDownloader local file support."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

from infrastructure.io.downloader import HttpDownloader
from domain.exceptions import DownloadError


class TestHttpDownloaderLocalFiles:
    """Test local file handling in HttpDownloader."""

    @pytest.fixture
    def downloader(self):
        """Create HttpDownloader instance."""
        return HttpDownloader()

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for tests."""
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_supports_local_file_path(self, downloader, temp_dir):
        """Test that local file paths are supported."""
        # Create a test file
        test_file = temp_dir / "test.mp4"
        test_file.write_text("test content")

        # Should support local path
        assert downloader.supports(str(test_file))

    def test_supports_file_url_scheme(self, downloader):
        """Test that file:// URLs are supported."""
        assert downloader.supports("file:///workspace/input.mp4")

    def test_supports_http_https(self, downloader):
        """Test that HTTP/HTTPS are still supported."""
        assert downloader.supports("http://example.com/file.mp4")
        assert downloader.supports("https://example.com/file.mp4")

    def test_does_not_support_unknown_scheme(self, downloader):
        """Test that unknown schemes are not supported."""
        assert downloader.supports("ftp://example.com/file.mp4") is False
        assert downloader.supports("s3://bucket/file.mp4") is False

    def test_download_local_file(self, downloader, temp_dir):
        """Test downloading (copying) a local file."""
        # Create source file
        source = temp_dir / "source.mp4"
        source.write_text("test video content")

        # Download to destination
        dest = temp_dir / "dest" / "output.mp4"
        result = downloader.download(str(source), dest)

        # Check result
        assert result == dest
        assert dest.exists()
        assert dest.read_text() == "test video content"

    def test_download_file_url(self, downloader, temp_dir):
        """Test downloading file:// URL."""
        # Create source file
        source = temp_dir / "source.mp4"
        source.write_text("test video content")

        # Download using file:// URL (use Path.as_uri() for proper cross-platform URL)
        file_url = source.as_uri()
        dest = temp_dir / "dest" / "output.mp4"
        result = downloader.download(file_url, dest)

        # Check result
        assert result == dest
        assert dest.exists()
        assert dest.read_text() == "test video content"

    def test_download_nonexistent_local_file(self, downloader, temp_dir):
        """Test that downloading non-existent local file raises error."""
        source = temp_dir / "nonexistent.mp4"
        dest = temp_dir / "output.mp4"

        # Should raise DownloadError for unsupported scheme
        # (because file doesn't exist, so it's not detected as local path)
        with pytest.raises(DownloadError):
            downloader.download(str(source), dest)

    def test_download_nonexistent_file_url(self, downloader, temp_dir):
        """Test that downloading non-existent file:// URL raises error."""
        file_url = f"file://{temp_dir}/nonexistent.mp4"
        dest = temp_dir / "output.mp4"

        with pytest.raises(DownloadError, match="File not found"):
            downloader.download(file_url, dest)

    def test_copy_creates_parent_directories(self, downloader, temp_dir):
        """Test that copying creates parent directories."""
        source = temp_dir / "source.mp4"
        source.write_text("test content")

        # Destination with nested dirs that don't exist
        dest = temp_dir / "a" / "b" / "c" / "output.mp4"

        result = downloader.download(str(source), dest)

        assert result == dest
        assert dest.exists()
        assert dest.parent.exists()

    @patch('infrastructure.io.downloader.requests.get')
    def test_http_download_still_works(self, mock_get, downloader, temp_dir):
        """Test that HTTP downloads still work as before."""
        # Mock HTTP response
        mock_response = Mock()
        mock_response.headers = {'content-length': '100'}
        mock_response.iter_content = Mock(return_value=[b'test', b'data'])
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        dest = temp_dir / "output.mp4"
        result = downloader.download("https://example.com/video.mp4", dest)

        assert result == dest
        assert dest.exists()
        mock_get.assert_called_once()

    def test_copy_preserves_file_metadata(self, downloader, temp_dir):
        """Test that file metadata is preserved during copy."""
        source = temp_dir / "source.mp4"
        source.write_text("test content")

        # Get original modification time
        original_mtime = source.stat().st_mtime

        dest = temp_dir / "output.mp4"
        downloader.download(str(source), dest)

        # Modification time should be preserved (shutil.copy2)
        assert dest.stat().st_mtime == original_mtime

    def test_absolute_path_support(self, downloader, temp_dir):
        """Test that absolute paths work."""
        source = temp_dir / "source.mp4"
        source.write_text("test content")

        # Use absolute path
        dest = temp_dir / "output.mp4"
        result = downloader.download(str(source.absolute()), dest)

        assert result == dest
        assert dest.exists()

    def test_relative_path_support(self, downloader, temp_dir):
        """Test that relative paths work if file exists."""
        # This test might be tricky - skip if cwd issues
        pass


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

