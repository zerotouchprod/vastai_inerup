"""
Cloudflare R2 storage client.

R2 полностью совместим с S3 API — используем boto3.
Отличие от B2: endpoint специфичен для аккаунта, регион фиксированный (auto).
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.client import Config
    from botocore.exceptions import ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment,misc]
    ClientError = Exception  # type: ignore[assignment,misc]
    BOTO3_AVAILABLE = False


@dataclass
class R2Credentials:
    access_key_id: str
    secret_access_key: str
    bucket: str
    endpoint: str
    region: str = "auto"

    @classmethod
    def from_env(cls) -> "R2Credentials":
        return cls(
            access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            bucket=os.environ["R2_BUCKET"],
            endpoint=os.environ["R2_ENDPOINT"],
            region=os.getenv("R2_DEFAULT_REGION", "auto"),
        )

    def is_configured(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key and self.bucket and self.endpoint)


class R2Client:
    """
    Cloudflare R2 client (S3-compatible via boto3).
    """

    def __init__(
        self,
        credentials: Optional[R2Credentials] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if not BOTO3_AVAILABLE:
            raise ImportError("boto3 is required: pip install boto3")

        self.creds = credentials or R2Credentials.from_env()
        self.logger = logger or logging.getLogger(__name__)

        self._s3 = boto3.client(
            "s3",
            endpoint_url=self.creds.endpoint,
            aws_access_key_id=self.creds.access_key_id,
            aws_secret_access_key=self.creds.secret_access_key,
            region_name=self.creds.region,
            config=Config(signature_version="s3v4"),
        )

    def upload_file(self, local_path: Path, key: str) -> str:
        """
        Upload file to R2.

        Returns:
            key — путь объекта в бакете
        """
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")

        size_mb = local_path.stat().st_size / 1024 ** 2
        self.logger.info(f"📤 Uploading {local_path.name} ({size_mb:.1f} MB) → r2://{self.creds.bucket}/{key}")

        self._s3.upload_file(
            Filename=str(local_path),
            Bucket=self.creds.bucket,
            Key=key,
        )

        self.logger.info(f"✅ Upload complete: {key}")
        return key

    def get_presigned_url(self, key: str, expires_in: int = 86400) -> str:
        """
        Generate presigned GET URL.

        Args:
            key: Object key in bucket
            expires_in: Seconds until expiry (default 24h)

        Returns:
            Presigned HTTPS URL
        """
        url: str = self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.creds.bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    def object_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.creds.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

