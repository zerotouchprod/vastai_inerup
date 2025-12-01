"""
B2 Storage domain models and protocols.

Domain layer for Backblaze B2 integration (SOLID).
"""

from dataclasses import dataclass
from typing import Optional, Protocol, List, Dict, Any
from pathlib import Path


@dataclass
class B2Object:
    """B2 object metadata."""
    key: str
    size: int
    last_modified: Optional[str] = None
    etag: Optional[str] = None

    @property
    def name(self) -> str:
        """Get object name (basename)."""
        return Path(self.key).name

    @property
    def stem(self) -> str:
        """Get object stem (name without extension)."""
        return Path(self.key).stem

    def __str__(self) -> str:
        return f"{self.key} ({self.size} bytes)"


@dataclass
class B2Credentials:
    """B2 credentials."""
    key_id: str
    application_key: str
    bucket: str
    endpoint: str = "https://s3.us-west-004.backblazeb2.com"

    @classmethod
    def from_env(cls) -> 'B2Credentials':
        """Load from environment variables."""
        import os
        return cls(
            key_id=os.getenv('B2_KEY', ''),
            application_key=os.getenv('B2_SECRET', ''),
            bucket=os.getenv('B2_BUCKET', ''),
            endpoint=os.getenv('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')
        )

    def validate(self) -> bool:
        """Check if credentials are set."""
        return bool(self.key_id and self.application_key and self.bucket)


class IB2Client(Protocol):
    """Protocol for B2 storage client."""

    def list_objects(
        self,
        prefix: str = '',
        max_keys: int = 1000
    ) -> List[B2Object]:
        """
        List objects in bucket.

        Args:
            prefix: Key prefix filter
            max_keys: Maximum objects to return

        Returns:
            List of objects
        """
        ...

    def upload_file(
        self,
        local_path: Path,
        key: str,
        progress_callback: Optional[callable] = None
    ) -> B2Object:
        """
        Upload file to B2.

        Args:
            local_path: Local file path
            key: Object key in bucket
            progress_callback: Optional callback(bytes_uploaded, total_bytes)

        Returns:
            Uploaded object metadata
        """
        ...

    def download_file(
        self,
        key: str,
        local_path: Path,
        progress_callback: Optional[callable] = None
    ) -> Path:
        """
        Download file from B2.

        Args:
            key: Object key in bucket
            local_path: Local file path
            progress_callback: Optional callback(bytes_downloaded, total_bytes)

        Returns:
            Downloaded file path
        """
        ...

    def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600
    ) -> str:
        """
        Get presigned GET URL for object.

        Args:
            key: Object key
            expires_in: Expiration time in seconds

        Returns:
            Presigned URL
        """
        ...

    def object_exists(self, key: str) -> bool:
        """
        Check if object exists.

        Args:
            key: Object key

        Returns:
            True if exists
        """
        ...

