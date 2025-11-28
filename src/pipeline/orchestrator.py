from dataclasses import dataclass
from typing import Optional
from ..config.schema import PipelineConfig
from ..io.extractor import FrameExtractor, ExtractResult
from ..models.rife_adapter import IInterpolator, InterpResult
from ..io.assembler import FrameAssembler, AssemblyResult
from ..io.uploader import IUploader, UploadResult


@dataclass
class JobResult:
    success: bool
    upload: Optional[UploadResult] = None


class PipelineOrchestrator:
    def __init__(self, cfg: PipelineConfig, extractor: FrameExtractor, interpolator: IInterpolator, assembler: FrameAssembler, uploader: IUploader):
        self.cfg = cfg
        self.extractor = extractor
        self.interpolator = interpolator
        self.assembler = assembler
        self.uploader = uploader

    def run(self, input_path: str, out_path: str) -> JobResult:
        # minimal flow: extract -> interp (noop) -> assemble (noop) -> upload (noop)
        er = self.extractor.extract_frames(input_path, "/tmp/work")
        ir = self.interpolator.run_batch("/tmp/work/input", "/tmp/work/output", factor=2, batch_cfg={})
        ar = self.assembler.assemble([], None, out_path, fps=30.0)
        up = self.uploader.upload(out_path, self.cfg.b2_bucket or "", "output/test.mp4")
        return JobResult(success=True, upload=up)

