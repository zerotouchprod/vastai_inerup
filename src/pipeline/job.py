from dataclasses import dataclass
from typing import Optional


@dataclass
class InputJob:
    job_id: str
    source_bucket: str
    source_key: str
    local_input_path: Optional[str] = None


@dataclass
class JobStatus:
    running: bool = False
    progress: float = 0.0


@dataclass
class JobResult:
    success: bool
    output_path: Optional[str] = None

