from dataclasses import dataclass
from typing import Optional

@dataclass
class PipelineConfig:
    input_path: Optional[str] = ''
    output_path: Optional[str] = ''
    scale: int = 2
    batch_size: Optional[int] = None
    auto_tune: bool = False
    # allow arbitrary additional attributes (tests set .target_fps etc.)
