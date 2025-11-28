from dataclasses import dataclass
from typing import Optional


@dataclass
class BatchResult:
    produced: int
    duration_s: Optional[float] = None
    exit_code: int = 0
    sample_files: Optional[list] = None


class BatchRunnerManager:
    def run(self, script_path: str, in_dir: str, out_dir: str, cfg: dict) -> BatchResult:
        # placeholder: run external script; for scaffold return success 0
        return BatchResult(produced=0, exit_code=0, sample_files=[])

