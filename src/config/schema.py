try:
    from pydantic import BaseModel
except Exception:  # pydantic may not be installed in test env
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

from typing import Optional


class PipelineConfig(BaseModel):
    source: Optional[str] = None
    target_fps: Optional[int] = None
    scale: Optional[int] = None
    b2_bucket: Optional[str] = None

    def dict(self):
        # provide minimal dict() for compatibility
        return {k: getattr(self, k, None) for k in ('source', 'target_fps', 'scale', 'b2_bucket')}
