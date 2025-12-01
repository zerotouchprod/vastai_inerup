"""File uploader implementations."""

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.client import Config
from botocore.exceptions import ClientError
from pathlib import Path
from typing import Optional, List

from domain.protocols import IUploader
from domain.models import UploadResult
from domain.exceptions import UploadError
from shared.logging import get_logger
from shared.retry import retry_with_backoff
from infrastructure.storage.pending_marker import PendingMarker

logger = get_logger(__name__)


class B2S3Uploader:
    """
    Uploader for Backblaze B2 using S3-compatible API.
    Implements IUploader protocol.
    """

    def __init__(
        self,
        bucket: str,
        endpoint: str,
        access_key: str,
        secret_key: str,
        region: Optional[str] = None,
        pending_marker: Optional[PendingMarker] = None
    ):
        """
        Initialize B2 S3 uploader.

        Args:
            bucket: S3 bucket name
            endpoint: S3 endpoint URL
            access_key: S3 access key
            secret_key: S3 secret key
            region: Optional region name
            pending_marker: Optional pending marker manager
        """
        self.bucket = bucket
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region

        self._client = self._create_client()
        self._pending_marker = pending_marker or PendingMarker()
        self._logger = get_logger(__name__)

        # Transfer config for multipart uploads
        self._transfer_config = TransferConfig(
            multipart_threshold=50 * 1024 * 1024,  # 50MB
            multipart_chunksize=50 * 1024 * 1024,   # 50MB
            max_concurrency=4,
            use_threads=True
        )

    def _create_client(self):
        """Create S3 client with B2-compatible configuration."""
        config = Config(
            signature_version='s3v4',
            s3={'addressing_style': 'virtual'}
        )

        kwargs = {
            'endpoint_url': self.endpoint,
            'aws_access_key_id': self.access_key,
            'aws_secret_access_key': self.secret_key,
            'config': config
        }

        if self.region:
            kwargs['region_name'] = self.region

        return boto3.client('s3', **kwargs)

    @retry_with_backoff(max_attempts=3, backoff_seconds=2)
    def upload(self, file_path: Path, key: str) -> UploadResult:
        """
        Upload a file to B2 storage.

        Args:
            file_path: Path to file to upload
            key: S3 object key

        Returns:
            UploadResult with upload details

        Raises:
            UploadError: If upload fails after retries
        """
        if not file_path.exists():
            raise UploadError(f"File not found: {file_path}")

        file_size = file_path.stat().st_size
        self._logger.info(
            f"Uploading {file_path} ({file_size} bytes) to "
            f"s3://{self.bucket}/{key}"
        )

        try:
            # Check if file already exists with same size
            try:
                head = self._client.head_object(Bucket=self.bucket, Key=key)
                remote_size = head.get('ContentLength', 0)

                if remote_size == file_size:
                    self._logger.info(
                        f"File already exists with matching size, skipping upload"
                    )
                    url = self._generate_presigned_url(key)
                    self._pending_marker.remove()

                    return UploadResult(
                        success=True,
                        url=url,
                        bucket=self.bucket,
                        key=key,
                        size_bytes=file_size
                    )
            except ClientError as e:
                if e.response['Error']['Code'] not in ('404', 'NoSuchKey', 'NotFound'):
                    raise

            # Upload file
            self._client.upload_file(
                str(file_path),
                self.bucket,
                key,
                Config=self._transfer_config
            )

            # Generate presigned URL
            url = self._generate_presigned_url(key)

            # Remove pending marker on success
            self._pending_marker.remove()

            self._logger.info(f"Upload successful: {key}")

            return UploadResult(
                success=True,
                url=url,
                bucket=self.bucket,
                key=key,
                size_bytes=file_size
            )

        except Exception as e:
            error_msg = f"Upload failed: {e}"
            self._logger.error(error_msg)

            # Save pending marker for retry
            self._pending_marker.save(
                file_path=file_path,
                bucket=self.bucket,
                key=key,
                endpoint=self.endpoint,
                attempts=1,  # Will be incremented on retry
                error=str(e)
            )

            raise UploadError(error_msg) from e

    def _generate_presigned_url(self, key: str, expires_in: int = 604800) -> str:
        """
        Generate presigned URL for object.

        Args:
            key: S3 object key
            expires_in: URL expiration time in seconds (default: 1 week)

        Returns:
            Presigned URL
        """
        return self._client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': key},
            ExpiresIn=expires_in
        )

    def resume_pending(self) -> List[UploadResult]:
        """
        Resume any pending uploads from previous runs.

        Returns:
            List of upload results
        """
        results = []

        pending = self._pending_marker.load()
        if not pending:
            self._logger.info("No pending uploads found")
            return results

        self._logger.info(f"Resuming pending upload: {pending.file_path}")

        try:
            file_path = Path(pending.file_path)

            if not file_path.exists():
                self._logger.error(f"Pending file not found: {file_path}")
                self._pending_marker.remove()
                return results

            result = self.upload(file_path, pending.key)
            results.append(result)

        except Exception as e:
            self._logger.error(f"Failed to resume pending upload: {e}")
            results.append(UploadResult(
                success=False,
                bucket=pending.bucket,
                key=pending.key,
                error=str(e)
            ))

        return results

