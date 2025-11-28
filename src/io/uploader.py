from dataclasses import dataclass
from typing import Optional

@dataclass
class UploadResult:
    success: bool
    key: Optional[str] = None
    url: Optional[str] = None
    attempts: int = 0

class IUploader:
    def upload(self, local_path: str, bucket: str, key: str) -> UploadResult:
        raise NotImplementedError

class DummyUploader(IUploader):
    def upload(self, local_path: str, bucket: str, key: str) -> UploadResult:
        return UploadResult(success=True, key=key, url=f"https://{bucket}.example/{key}", attempts=1)

