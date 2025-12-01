"""Tests for B2S3Uploader."""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call
import tempfile
import shutil
from botocore.exceptions import ClientError

from infrastructure.io.uploader import B2S3Uploader
from domain.models import UploadResult
from domain.exceptions import UploadError


class TestB2S3Uploader:
    """Test B2S3Uploader implementation."""

    @pytest.fixture
    def uploader(self):
        """Create uploader instance with mocked client."""
        with patch('infrastructure.io.uploader.boto3.client') as mock_boto:
            mock_client = Mock()
            mock_boto.return_value = mock_client

            uploader = B2S3Uploader(
                bucket='test-bucket',
                endpoint='https://s3.us-west-004.backblazeb2.com',
                access_key='test-key',
                secret_key='test-secret'
            )
            uploader._client = mock_client
            yield uploader

    @pytest.fixture
    def temp_file(self):
        """Create temporary file for testing."""
        tmpdir = Path(tempfile.mkdtemp())
        test_file = tmpdir / "test.mp4"
        test_file.write_text("test video content")
        yield test_file
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_init_creates_client(self):
        """Test that initialization creates S3 client."""
        with patch('infrastructure.io.uploader.boto3.client') as mock_boto:
            mock_client = Mock()
            mock_boto.return_value = mock_client

            uploader = B2S3Uploader(
                bucket='test-bucket',
                endpoint='https://s3.us-west-004.backblazeb2.com',
                access_key='test-key',
                secret_key='test-secret'
            )

            # Should call boto3.client
            mock_boto.assert_called_once()
            assert uploader.bucket == 'test-bucket'
            assert uploader.endpoint == 'https://s3.us-west-004.backblazeb2.com'

    def test_upload_success(self, uploader, temp_file):
        """Test successful upload."""
        # Mock S3 responses
        uploader._client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject'
        )
        uploader._client.upload_file.return_value = None
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        # Upload file
        result = uploader.upload(temp_file, 'videos/test.mp4')

        # Check result
        assert result.success is True
        assert result.bucket == 'test-bucket'
        assert result.key == 'videos/test.mp4'
        assert result.url == 'https://example.com/video.mp4'
        assert result.size_bytes > 0

        # Check that upload_file was called
        uploader._client.upload_file.assert_called_once()

    def test_upload_file_not_found(self, uploader):
        """Test upload with non-existent file."""
        fake_file = Path('/nonexistent/file.mp4')

        with pytest.raises(UploadError, match="File not found"):
            uploader.upload(fake_file, 'test.mp4')

    def test_upload_skips_if_already_exists(self, uploader, temp_file):
        """Test that upload is skipped if file exists with same size."""
        file_size = temp_file.stat().st_size

        # Mock head_object to return existing file with same size
        uploader._client.head_object.return_value = {
            'ContentLength': file_size
        }
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        result = uploader.upload(temp_file, 'videos/test.mp4')

        # Should skip upload
        assert result.success is True
        uploader._client.upload_file.assert_not_called()

        # Should still generate presigned URL
        uploader._client.generate_presigned_url.assert_called_once()

    def test_upload_overwrites_if_size_differs(self, uploader, temp_file):
        """Test that upload proceeds if remote file has different size."""
        file_size = temp_file.stat().st_size

        # Mock head_object to return existing file with different size
        uploader._client.head_object.return_value = {
            'ContentLength': file_size + 100  # Different size
        }
        uploader._client.upload_file.return_value = None
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        result = uploader.upload(temp_file, 'videos/test.mp4')

        # Should upload anyway
        assert result.success is True
        uploader._client.upload_file.assert_called_once()

    def test_upload_handles_client_error(self, uploader, temp_file):
        """Test upload error handling."""
        # Mock upload to fail
        uploader._client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject'
        )
        uploader._client.upload_file.side_effect = Exception("Network error")

        with pytest.raises(UploadError, match="Upload failed"):
            uploader.upload(temp_file, 'videos/test.mp4')

    def test_generate_presigned_url(self, uploader):
        """Test presigned URL generation."""
        uploader._client.generate_presigned_url.return_value = 'https://presigned.url'

        url = uploader._generate_presigned_url('test.mp4')

        assert url == 'https://presigned.url'
        uploader._client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'test.mp4'},
            ExpiresIn=604800
        )

    def test_generate_presigned_url_custom_expiry(self, uploader):
        """Test presigned URL with custom expiry."""
        uploader._client.generate_presigned_url.return_value = 'https://presigned.url'

        url = uploader._generate_presigned_url('test.mp4', expires_in=3600)

        uploader._client.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'test.mp4'},
            ExpiresIn=3600
        )

    def test_upload_with_region(self):
        """Test that region is passed to boto3 client."""
        with patch('infrastructure.io.uploader.boto3.client') as mock_boto:
            mock_client = Mock()
            mock_boto.return_value = mock_client

            uploader = B2S3Uploader(
                bucket='test-bucket',
                endpoint='https://s3.us-west-004.backblazeb2.com',
                access_key='test-key',
                secret_key='test-secret',
                region='us-west-004'
            )

            # Check that boto3.client was called with region
            call_kwargs = mock_boto.call_args[1]
            assert call_kwargs.get('region_name') == 'us-west-004'

    def test_upload_uses_transfer_config(self, uploader, temp_file):
        """Test that upload uses transfer config for multipart uploads."""
        uploader._client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject'
        )
        uploader._client.upload_file.return_value = None
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        uploader.upload(temp_file, 'videos/test.mp4')

        # Check that upload_file was called with Config parameter
        call_kwargs = uploader._client.upload_file.call_args[1]
        assert 'Config' in call_kwargs

    def test_resume_pending_no_pending_uploads(self, uploader):
        """Test resume_pending with no pending uploads."""
        with patch.object(uploader._pending_marker, 'load', return_value=None):
            results = uploader.resume_pending()

            assert results == []

    def test_resume_pending_success(self, uploader, temp_file):
        """Test successful resume of pending upload."""
        pending_mock = Mock()
        pending_mock.file_path = str(temp_file)
        pending_mock.key = 'videos/test.mp4'
        pending_mock.bucket = 'test-bucket'

        with patch.object(uploader._pending_marker, 'load', return_value=pending_mock):
            uploader._client.head_object.side_effect = ClientError(
                {'Error': {'Code': '404'}}, 'HeadObject'
            )
            uploader._client.upload_file.return_value = None
            uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

            results = uploader.resume_pending()

            assert len(results) == 1
            assert results[0].success is True

    def test_resume_pending_file_not_found(self, uploader):
        """Test resume_pending when file no longer exists."""
        pending_mock = Mock()
        pending_mock.file_path = '/nonexistent/file.mp4'
        pending_mock.key = 'videos/test.mp4'
        pending_mock.bucket = 'test-bucket'

        with patch.object(uploader._pending_marker, 'load', return_value=pending_mock):
            with patch.object(uploader._pending_marker, 'remove') as mock_remove:
                results = uploader.resume_pending()

                # Should remove pending marker
                mock_remove.assert_called_once()
                assert results == []

    def test_retry_on_transient_errors(self, uploader, temp_file):
        """Test that upload retries on transient errors."""
        # First two calls fail, third succeeds
        uploader._client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject'
        )
        uploader._client.upload_file.side_effect = [
            Exception("Network timeout"),
            Exception("Connection reset"),
            None  # Success on 3rd attempt
        ]
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        result = uploader.upload(temp_file, 'videos/test.mp4')

        # Should succeed after retries
        assert result.success is True
        assert uploader._client.upload_file.call_count == 3

    def test_upload_result_contains_all_fields(self, uploader, temp_file):
        """Test that UploadResult contains all required fields."""
        uploader._client.head_object.side_effect = ClientError(
            {'Error': {'Code': '404'}}, 'HeadObject'
        )
        uploader._client.upload_file.return_value = None
        uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

        result = uploader.upload(temp_file, 'videos/test.mp4')

        # Check all fields
        assert hasattr(result, 'success')
        assert hasattr(result, 'bucket')
        assert hasattr(result, 'key')
        assert hasattr(result, 'url')
        assert hasattr(result, 'size_bytes')

        assert result.success is True
        assert result.bucket == 'test-bucket'
        assert result.key == 'videos/test.mp4'
        assert result.url == 'https://example.com/video.mp4'
        assert result.size_bytes > 0


class TestB2S3UploaderPendingMarker:
    """Test pending marker functionality."""

    @pytest.fixture
    def uploader(self):
        """Create uploader with mocked pending marker."""
        with patch('infrastructure.io.uploader.boto3.client'):
            mock_marker = Mock()
            uploader = B2S3Uploader(
                bucket='test-bucket',
                endpoint='https://s3.us-west-004.backblazeb2.com',
                access_key='test-key',
                secret_key='test-secret',
                pending_marker=mock_marker
            )
            yield uploader

    def test_pending_marker_saved_on_error(self, uploader):
        """Test that pending marker is saved on upload error."""
        test_file = Path('/tmp/test.mp4')

        # Mock file existence check
        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'stat') as mock_stat:
                mock_stat.return_value.st_size = 1000

                uploader._client.head_object.side_effect = ClientError(
                    {'Error': {'Code': '404'}}, 'HeadObject'
                )
                uploader._client.upload_file.side_effect = Exception("Network error")

                with pytest.raises(UploadError):
                    uploader.upload(test_file, 'videos/test.mp4')

                # Pending marker should be saved (3 times due to retries)
                assert uploader._pending_marker.save.call_count == 3

    def test_pending_marker_removed_on_success(self, uploader):
        """Test that pending marker is removed on successful upload."""
        test_file = Path('/tmp/test.mp4')

        with patch.object(Path, 'exists', return_value=True):
            with patch.object(Path, 'stat') as mock_stat:
                mock_stat.return_value.st_size = 1000

                uploader._client.head_object.side_effect = ClientError(
                    {'Error': {'Code': '404'}}, 'HeadObject'
                )
                uploader._client.upload_file.return_value = None
                uploader._client.generate_presigned_url.return_value = 'https://example.com/video.mp4'

                uploader.upload(test_file, 'videos/test.mp4')

                # Pending marker should be removed
                uploader._pending_marker.remove.assert_called_once()


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

