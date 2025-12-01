"""Pending upload marker management."""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

from shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PendingUpload:
    """Represents a pending upload operation."""

    file_path: str
    bucket: str
    key: str
    endpoint: str
    attempts: int
    timestamp: int
    job_id: Optional[str] = None
    error: Optional[str] = None


class PendingMarker:
    """Manages pending upload markers for retry logic."""

    def __init__(self, marker_path: Optional[Path] = None):
        """
        Initialize pending marker manager.

        Args:
            marker_path: Path to marker file (default: /workspace/.pending_upload.json)
        """
        self.marker_path = marker_path or Path("/workspace/.pending_upload.json")
        self._logger = get_logger(__name__)

    def save(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        endpoint: str,
        attempts: int,
        job_id: Optional[str] = None,
        error: Optional[str] = None
    ) -> None:
        """
        Save a pending upload marker.

        Args:
            file_path: Path to file to upload
            bucket: S3 bucket name
            key: S3 object key
            endpoint: S3 endpoint URL
            attempts: Number of attempts made
            job_id: Optional job identifier
            error: Optional error message
        """
        marker = PendingUpload(
            file_path=str(file_path),
            bucket=bucket,
            key=key,
            endpoint=endpoint,
            attempts=attempts,
            timestamp=int(time.time()),
            job_id=job_id,
            error=error
        )

        try:
            self.marker_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.marker_path, 'w') as f:
                json.dump(asdict(marker), f, indent=2)

            self._logger.info(f"Saved pending upload marker: {self.marker_path}")

        except Exception as e:
            self._logger.error(f"Failed to save pending marker: {e}")

    def load(self) -> Optional[PendingUpload]:
        """
        Load pending upload marker if exists.

        Returns:
            PendingUpload if marker exists, None otherwise
        """
        if not self.marker_path.exists():
            return None

        try:
            with open(self.marker_path, 'r') as f:
                data = json.load(f)

            marker = PendingUpload(**data)
            self._logger.info(f"Loaded pending upload marker: {marker.file_path}")
            return marker

        except Exception as e:
            self._logger.error(f"Failed to load pending marker: {e}")
            return None

    def remove(self) -> None:
        """Remove pending upload marker."""
        if self.marker_path.exists():
            try:
                self.marker_path.unlink()
                self._logger.info(f"Removed pending upload marker")
            except Exception as e:
                self._logger.error(f"Failed to remove pending marker: {e}")

    def exists(self) -> bool:
        """Check if pending marker exists."""
        return self.marker_path.exists()

