"""
Unit tests for B2 Storage client.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import tempfile
import shutil

from infrastructure.storage.b2_client import B2Client
from domain.b2_storage import B2Object, B2Credentials
from domain.exceptions import VideoProcessingError


@pytest.fixture
def temp_dir():
    """Provide temporary directory."""
    temp = tempfile.mkdtemp(prefix="b2_test_")
    yield Path(temp)
    shutil.rmtree(temp, ignore_errors=True)


@pytest.fixture
def mock_credentials():
    """Provide mock B2 credentials."""
    return B2Credentials(
        key_id="test_key_id",
        application_key="test_app_key",
        bucket="test-bucket",
        endpoint="https://s3.us-west-004.backblazeb2.com"
    )


class TestB2Credentials:
    """Test B2Credentials model."""

    def test_create_credentials(self):
        """Test creating credentials."""
        creds = B2Credentials(
            key_id="key123",
            application_key="secret456",
            bucket="my-bucket",
            endpoint="https://s3.example.com"
        )

        assert creds.key_id == "key123"
        assert creds.application_key == "secret456"
        assert creds.bucket == "my-bucket"
        assert creds.endpoint == "https://s3.example.com"

    def test_credentials_from_env(self, monkeypatch):
        """Test loading credentials from environment."""
        monkeypatch.setenv('B2_KEY', 'env_key')
        monkeypatch.setenv('B2_SECRET', 'env_secret')
        monkeypatch.setenv('B2_BUCKET', 'env-bucket')
        monkeypatch.setenv('B2_ENDPOINT', 'https://s3.custom.com')

        creds = B2Credentials.from_env()

        assert creds.key_id == 'env_key'
        assert creds.application_key == 'env_secret'
        assert creds.bucket == 'env-bucket'
        assert creds.endpoint == 'https://s3.custom.com'

    def test_credentials_validate(self):
        """Test credentials validation."""
        # Valid credentials
        creds = B2Credentials(
            key_id="key",
            application_key="secret",
            bucket="bucket"
        )
        assert creds.validate() is True

        # Invalid - empty key_id
        creds_invalid = B2Credentials(
            key_id="",
            application_key="secret",
            bucket="bucket"
        )
        assert creds_invalid.validate() is False


class TestB2Object:
    """Test B2Object model."""

    def test_create_object(self):
        """Test creating B2 object."""
        obj = B2Object(
            key="folder/video.mp4",
            size=1024000,
            last_modified="2025-12-01T10:00:00Z",
            etag="abc123"
        )

        assert obj.key == "folder/video.mp4"
        assert obj.size == 1024000
        assert obj.last_modified == "2025-12-01T10:00:00Z"
        assert obj.etag == "abc123"

    def test_object_name_property(self):
        """Test getting object name."""
        obj = B2Object(
            key="folder/subfolder/video.mp4",
            size=1000
        )

        assert obj.name == "video.mp4"

    def test_object_stem_property(self):
        """Test getting object stem."""
        obj = B2Object(
            key="folder/video.mp4",
            size=1000
        )

        assert obj.stem == "video"

    def test_object_str_representation(self):
        """Test string representation."""
        obj = B2Object(
            key="test.mp4",
            size=500
        )

        assert str(obj) == "test.mp4 (500 bytes)"


@patch('infrastructure.storage.b2_client.boto3')
class TestB2Client:
    """Test B2Client implementation."""

    def test_initialization_with_credentials(self, mock_boto3, mock_credentials):
        """Test client initialization with credentials."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        client = B2Client(credentials=mock_credentials)

        assert client.bucket == "test-bucket"
        mock_boto3.client.assert_called_once_with(
            's3',
            endpoint_url="https://s3.us-west-004.backblazeb2.com",
            aws_access_key_id="test_key_id",
            aws_secret_access_key="test_app_key"
        )

    def test_initialization_from_env(self, mock_boto3, monkeypatch):
        """Test client initialization from environment."""
        monkeypatch.setenv('B2_KEY', 'env_key')
        monkeypatch.setenv('B2_SECRET', 'env_secret')
        monkeypatch.setenv('B2_BUCKET', 'env-bucket')

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        client = B2Client()

        assert client.bucket == "env-bucket"

    def test_initialization_fails_without_credentials(self, mock_boto3):
        """Test client initialization fails without credentials."""
        with pytest.raises(ValueError, match="B2 credentials not set"):
            B2Client()

    def test_list_objects(self, mock_boto3, mock_credentials):
        """Test listing objects."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        # Mock response
        mock_s3.list_objects_v2.return_value = {
            'Contents': [
                {
                    'Key': 'video1.mp4',
                    'Size': 1000,
                    'LastModified': '2025-12-01T10:00:00Z',
                    'ETag': '"abc123"'
                },
                {
                    'Key': 'video2.mp4',
                    'Size': 2000,
                    'LastModified': '2025-12-01T11:00:00Z',
                    'ETag': '"def456"'
                }
            ]
        }

        client = B2Client(credentials=mock_credentials)
        objects = client.list_objects(prefix='videos/')

        assert len(objects) == 2
        assert objects[0].key == 'video1.mp4'
        assert objects[0].size == 1000
        assert objects[0].etag == 'abc123'
        assert objects[1].key == 'video2.mp4'

    def test_list_objects_empty(self, mock_boto3, mock_credentials):
        """Test listing objects when bucket is empty."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.return_value = {}

        client = B2Client(credentials=mock_credentials)
        objects = client.list_objects()

        assert len(objects) == 0

    def test_upload_file(self, mock_boto3, mock_credentials, temp_dir):
        """Test uploading file."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        # Create test file
        test_file = temp_dir / "test.mp4"
        test_file.write_bytes(b"test video content")

        client = B2Client(credentials=mock_credentials)
        result = client.upload_file(test_file, "uploads/test.mp4")

        assert result.key == "uploads/test.mp4"
        assert result.size == 18  # Length of "test video content"
        mock_s3.upload_file.assert_called_once()

    def test_upload_file_with_progress(self, mock_boto3, mock_credentials, temp_dir):
        """Test uploading file with progress callback."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        test_file = temp_dir / "test.mp4"
        test_file.write_bytes(b"test content")

        progress_calls = []
        def progress_cb(current, total):
            progress_calls.append((current, total))

        client = B2Client(credentials=mock_credentials)
        client.upload_file(test_file, "test.mp4", progress_callback=progress_cb)

        # Verify progress callback was configured
        mock_s3.upload_file.assert_called_once()

    def test_upload_file_not_found(self, mock_boto3, mock_credentials, temp_dir):
        """Test uploading non-existent file fails."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        client = B2Client(credentials=mock_credentials)

        with pytest.raises(FileNotFoundError):
            client.upload_file(temp_dir / "nonexistent.mp4", "test.mp4")

    def test_download_file(self, mock_boto3, mock_credentials, temp_dir):
        """Test downloading file."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        # Mock head_object to return file size
        mock_s3.head_object.return_value = {'ContentLength': 1000}

        download_path = temp_dir / "downloaded.mp4"

        client = B2Client(credentials=mock_credentials)
        result = client.download_file("videos/test.mp4", download_path)

        assert result == download_path
        mock_s3.download_file.assert_called_once()

    def test_get_presigned_url(self, mock_boto3, mock_credentials):
        """Test generating presigned URL."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.generate_presigned_url.return_value = "https://example.com/signed-url"

        client = B2Client(credentials=mock_credentials)
        url = client.get_presigned_url("videos/test.mp4", expires_in=7200)

        assert url == "https://example.com/signed-url"
        mock_s3.generate_presigned_url.assert_called_once_with(
            'get_object',
            Params={'Bucket': 'test-bucket', 'Key': 'videos/test.mp4'},
            ExpiresIn=7200
        )

    def test_object_exists_true(self, mock_boto3, mock_credentials):
        """Test checking object exists returns True."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.head_object.return_value = {'ContentLength': 1000}

        client = B2Client(credentials=mock_credentials)
        exists = client.object_exists("videos/test.mp4")

        assert exists is True

    def test_object_exists_false(self, mock_boto3, mock_credentials):
        """Test checking object exists returns False for 404."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        from botocore.exceptions import ClientError
        error = ClientError(
            {'Error': {'Code': '404'}},
            'HeadObject'
        )
        mock_s3.head_object.side_effect = error

        client = B2Client(credentials=mock_credentials)
        exists = client.object_exists("videos/nonexistent.mp4")

        assert exists is False

    def test_upload_failure_raises_error(self, mock_boto3, mock_credentials, temp_dir):
        """Test upload failure raises VideoProcessingError."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        test_file = temp_dir / "test.mp4"
        test_file.write_bytes(b"content")

        mock_s3.upload_file.side_effect = Exception("Network error")

        client = B2Client(credentials=mock_credentials)

        with pytest.raises(VideoProcessingError, match="Upload failed"):
            client.upload_file(test_file, "test.mp4")

    def test_list_objects_failure_raises_error(self, mock_boto3, mock_credentials):
        """Test list objects failure raises VideoProcessingError."""
        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        mock_s3.list_objects_v2.side_effect = Exception("API error")

        client = B2Client(credentials=mock_credentials)

        with pytest.raises(VideoProcessingError, match="Failed to list objects"):
            client.list_objects()

