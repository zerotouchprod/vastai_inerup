"""
B2 Storage client implementation.

Infrastructure layer for Backblaze B2 integration using boto3 (S3-compatible API).
"""

import os
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging

from domain.b2_storage import (
    IB2Client,
    B2Object,
    B2Credentials
)
from domain.exceptions import VideoProcessingError

try:
    import boto3
    from botocore.exceptions import ClientError, BotoCoreError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


class B2Client:
    """
    B2 Storage client implementation using boto3 (S3-compatible API).

    Backblaze B2 supports S3-compatible API, so we use boto3.
    """

    def __init__(
        self,
        credentials: Optional[B2Credentials] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize B2 client.

        Args:
            credentials: B2 credentials (loads from env if None)
            logger: Logger instance
        """
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 library required. Install: pip install boto3")

        self.credentials = credentials or B2Credentials.from_env()
        if not self.credentials.validate():
            raise ValueError("B2 credentials not set (B2_KEY, B2_SECRET, B2_BUCKET)")

        self.logger = logger or logging.getLogger(__name__)

        # Create boto3 client
        self.s3 = boto3.client(
            's3',
            endpoint_url=self.credentials.endpoint,
            aws_access_key_id=self.credentials.key_id,
            aws_secret_access_key=self.credentials.application_key,
        )

        self.bucket = self.credentials.bucket

    def list_objects(
        self,
        prefix: str = '',
        max_keys: int = 1000
    ) -> List[B2Object]:
        """List objects in bucket."""
        self.logger.info(f"Listing objects: bucket={self.bucket}, prefix={prefix}")

        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=max_keys
            )

            objects = []
            for item in response.get('Contents', []):
                obj = B2Object(
                    key=item['Key'],
                    size=item['Size'],
                    last_modified=str(item.get('LastModified', '')),
                    etag=item.get('ETag', '').strip('"')
                )
                objects.append(obj)

            self.logger.info(f"Found {len(objects)} objects")
            return objects

        except Exception as e:
            error_msg = f"Failed to list objects: {e}"
            self.logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

    def upload_file(
        self,
        local_path: Path,
        key: str,
        progress_callback: Optional[callable] = None
    ) -> B2Object:
        """Upload file to B2."""
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")

        file_size = local_path.stat().st_size
        self.logger.info(f"Uploading {local_path} -> s3://{self.bucket}/{key} ({file_size} bytes)")

        try:
            # Upload with progress callback if provided
            if progress_callback:
                def callback(bytes_uploaded):
                    progress_callback(bytes_uploaded, file_size)

                self.s3.upload_file(
                    str(local_path),
                    self.bucket,
                    key,
                    Callback=callback
                )
            else:
                self.s3.upload_file(
                    str(local_path),
                    self.bucket,
                    key
                )

            self.logger.info(f"Upload completed: {key}")

            # Return object metadata
            return B2Object(
                key=key,
                size=file_size
            )

        except Exception as e:
            error_msg = f"Upload failed: {e}"
            self.logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

    def download_file(
        self,
        key: str,
        local_path: Path,
        progress_callback: Optional[callable] = None
    ) -> Path:
        """Download file from B2."""
        self.logger.info(f"Downloading s3://{self.bucket}/{key} -> {local_path}")

        try:
            # Get object size
            response = self.s3.head_object(Bucket=self.bucket, Key=key)
            file_size = response['ContentLength']

            # Ensure parent directory exists
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # Download with progress callback if provided
            if progress_callback:
                def callback(bytes_downloaded):
                    progress_callback(bytes_downloaded, file_size)

                self.s3.download_file(
                    self.bucket,
                    key,
                    str(local_path),
                    Callback=callback
                )
            else:
                self.s3.download_file(
                    self.bucket,
                    key,
                    str(local_path)
                )

            self.logger.info(f"Download completed: {local_path}")
            return local_path

        except Exception as e:
            error_msg = f"Download failed: {e}"
            self.logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

    def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600
    ) -> str:
        """Get presigned GET URL for object."""
        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': key
                },
                ExpiresIn=expires_in
            )

            self.logger.debug(f"Generated presigned URL for {key}")
            return url

        except Exception as e:
            error_msg = f"Failed to generate presigned URL: {e}"
            self.logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

    def object_exists(self, key: str) -> bool:
        """Check if object exists."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise
        except Exception as e:
            self.logger.warning(f"Error checking object existence: {e}")
            return False

