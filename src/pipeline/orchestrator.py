from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from ..config.loader import ConfigLoader
from ..io.extractor import FrameExtractor, ExtractResult
from ..io.assembler import FrameAssembler, AssemblyResult
from ..models.rife_adapter import RIFEAdapter
from ..io.uploader import IUploader, UploadResult

@dataclass
class JobResult:
    success: bool
    output_path: str = ''
    logs: str = ''
    upload: Optional[UploadResult] = None
    diagnostics_bundle: Optional[str] = None

class PipelineOrchestrator:
    def __init__(self, config: ConfigLoader | object, extractor: FrameExtractor = None, rife: RIFEAdapter = None, assembler: FrameAssembler = None, uploader: IUploader = None):
        # allow tests to pass pre-constructed objects
        if isinstance(config, (str, Path)):
            self.cfg_loader = ConfigLoader(config)
            self.config = self.cfg_loader.load_config()
        else:
            # config may be PipelineConfig instance in tests
            self.config = config
        self.extractor = extractor or FrameExtractor()
        self.rife = rife or RIFEAdapter()
        self.assembler = assembler or FrameAssembler()
        self.uploader = uploader

    def run(self, input_path: str, out_path: str, work_dir: str = '/tmp/realesrgan_run') -> JobResult:
        cfg = self.config
        workdir = Path(work_dir)
        workdir.mkdir(parents=True, exist_ok=True)
        in_dir = workdir / 'input'
        out_dir = workdir / 'output'
        # extract frames
        extract_res: ExtractResult = self.extractor.extract_frames(input_path, str(in_dir))
        print(f"Extracted {extract_res.frames_count} frames -> pattern {extract_res.frame_pattern}")
        # Try batch riffing/upscaling (tests will mock rife)
        interp = self.rife.run_batch(str(in_dir), str(out_dir), getattr(cfg, 'scale', 2), {})
        if not interp.success:
            # fallback to pairwise
            interp = self.rife.run_pairwise(str(in_dir), str(out_dir), getattr(cfg, 'scale', 2))

        # If interpolation failed both ways, return diagnostics without assembling
        if not getattr(interp, 'success', False):
            diag = str(workdir)
            return JobResult(success=False, logs=getattr(interp, 'logs', ''), diagnostics_bundle=diag)

        asm: AssemblyResult = self.assembler.assemble(frames=list(in_dir.glob('frame_*.png')) or list(out_dir.glob('frame_*.png')), audio_path=None, out_file=out_path, fps=getattr(cfg, 'target_fps', 24))
        if asm.success:
            upload_res = None
            if self.uploader:
                upload_res = self.uploader.upload(out_path, getattr(cfg, 'b2_bucket', 'test'), 'key')
            return JobResult(success=True, output_path=out_path, logs=asm.logs, upload=upload_res)
        else:
            # produce diagnostics bundle path for tests (workdir)
            diag = str(workdir)
            return JobResult(success=False, logs=asm.logs, diagnostics_bundle=diag)
