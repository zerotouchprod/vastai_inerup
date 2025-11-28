from dataclasses import dataclass
from typing import Optional, List
import os
import shutil
import tempfile
import json
import tarfile
from datetime import datetime

from ..config.schema import PipelineConfig
from ..io.extractor import FrameExtractor, ExtractResult
from ..models.rife_adapter import IInterpolator, InterpResult, RIFEAdapter
from ..io.assembler import FrameAssembler, AssemblyResult
from ..io.uploader import IUploader, UploadResult


@dataclass
class JobResult:
    success: bool
    upload: Optional[UploadResult] = None
    diagnostics_bundle: Optional[str] = None


class PipelineOrchestrator:
    def __init__(self, cfg: PipelineConfig, extractor: FrameExtractor, interpolator: IInterpolator, assembler: FrameAssembler, uploader: IUploader):
        self.cfg = cfg
        self.extractor = extractor
        self.interpolator = interpolator
        self.assembler = assembler
        self.uploader = uploader

    def _make_workdir(self, base: Optional[str] = None) -> str:
        if base:
            os.makedirs(base, exist_ok=True)
            return base
        return tempfile.mkdtemp(prefix="pipeline_work_")

    def _save_diagnostics(self, workdir: str, name: str, logs: dict) -> str:
        logs_dir = os.path.join(workdir, "diagnostics")
        os.makedirs(logs_dir, exist_ok=True)
        manifest = {"created": datetime.utcnow().isoformat(), "name": name}
        for k, v in logs.items():
            path = os.path.join(logs_dir, f"{k}.log")
            try:
                with open(path, "w") as f:
                    if isinstance(v, str):
                        f.write(v)
                    else:
                        json.dump(v, f, indent=2)
            except Exception:
                pass
            manifest[k] = path
        manifest_path = os.path.join(logs_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        # tar.gz the diagnostics
        bundle = os.path.join(workdir, f"diagnostics_{name}.tar.gz")
        with tarfile.open(bundle, "w:gz") as tar:
            tar.add(logs_dir, arcname=os.path.basename(logs_dir))
        return bundle

    def run(self, input_path: str, out_path: str, work_dir: Optional[str] = None) -> JobResult:
        workdir = self._make_workdir(work_dir)
        # progress file
        progress_path = os.path.join(workdir, 'progress.json')
        def write_progress(step: str, info: dict):
            p = {'step': step, 'time': datetime.utcnow().isoformat()}
            p.update(info)
            try:
                with open(progress_path, 'w') as pf:
                    json.dump(p, pf)
            except Exception:
                pass
        # extractor.extract_frames writes into workdir/input and workdir/output
        try:
            extract_res: ExtractResult = self.extractor.extract_frames(input_path, workdir)
            write_progress('extraction', {'frames_count': extract_res.frames_count})
        except Exception as e:
            diagnostics = {"extractor": str(e)}
            bundle = self._save_diagnostics(workdir, "extract_fail", diagnostics)
            return JobResult(success=False, diagnostics_bundle=bundle)

        # basic validation
        if extract_res.frames_count < 2:
            diagnostics = {"extractor": extract_res.logs}
            bundle = self._save_diagnostics(workdir, "not_enough_frames", diagnostics)
            return JobResult(success=False, diagnostics_bundle=bundle)

        # derive factor heuristically
        factor = 2
        if getattr(self.cfg, 'target_fps', None):
            try:
                orig = 24.0
                factor = max(1, int(round(self.cfg.target_fps / orig)))
            except Exception:
                factor = 2

        # Try batch interpolation first
        batch_logs = {}
        in_dir = os.path.join(workdir, 'input')
        out_dir = os.path.join(workdir, 'output')
        os.makedirs(out_dir, exist_ok=True)

        batch_res: InterpResult = InterpResult(mids_count=0, success=False, logs='')
        try:
            # pass batch_cfg from config if available
            cfg_batch = getattr(self.cfg, 'batch_cfg', {}) or {}
            batch_res = self.interpolator.run_batch(in_dir, out_dir, factor, batch_cfg=cfg_batch)
            write_progress('batch_started', {'batch_cfg': cfg_batch})
        except Exception as e:
            batch_res = InterpResult(mids_count=0, success=False, logs=str(e))
        batch_logs['batch'] = batch_res.logs or ''
        write_progress('batch_complete', {'mids_count': batch_res.mids_count, 'success': batch_res.success})

        # If batch succeeded and produced mids, assemble directly
        if batch_res.success and batch_res.mids_count > 0:
            # assemble using produced mids (out_dir)
            frames = sorted([os.path.join(out_dir, p) for p in os.listdir(out_dir) if p.lower().endswith(('.png', '.jpg', '.jpeg'))])
            asm_res: AssemblyResult = self.assembler.assemble(frames, extract_res.audio_path, out_path, fps=(self.cfg.target_fps or 24.0))
            if asm_res.success:
                # upload
                up: UploadResult = self.uploader.upload(out_path, self.cfg.b2_bucket or "", os.path.basename(out_path))
                write_progress('uploaded', {'key': getattr(up, 'key', None), 'url': getattr(up, 'url', None)})
                return JobResult(success=True, upload=up)
            else:
                # assembler failed after batch produced outputs -> diagnostics
                diagnostics = {'extractor': extract_res.logs, 'batch': batch_res.logs, 'assembler': asm_res.logs}
                bundle = self._save_diagnostics(workdir, 'assemble_after_batch_fail', diagnostics)
                return JobResult(success=False, diagnostics_bundle=bundle)

        # Batch failed or produced nothing -> fallback to per-pair
        pair_res: InterpResult = InterpResult(mids_count=0, success=False, logs='')
        try:
            pair_res = self.interpolator.run_pairwise(in_dir, out_dir, factor)
            write_progress('pairwise_complete', {'mids_count': pair_res.mids_count, 'success': pair_res.success})
        except Exception as e:
            pair_res = InterpResult(mids_count=0, success=False, logs=str(e))
        batch_logs['pairwise'] = pair_res.logs or ''

        if pair_res.success and pair_res.mids_count > 0:
            frames = sorted([os.path.join(out_dir, p) for p in os.listdir(out_dir) if p.lower().endswith(('.png', '.jpg', '.jpeg'))])
            asm_res = self.assembler.assemble(frames, extract_res.audio_path, out_path, fps=(self.cfg.target_fps or 24.0))
            if asm_res.success:
                up = self.uploader.upload(out_path, self.cfg.b2_bucket or "", os.path.basename(out_path))
                write_progress('uploaded', {'key': getattr(up, 'key', None), 'url': getattr(up, 'url', None)})
                return JobResult(success=True, upload=up)
            else:
                diagnostics = {'extractor': extract_res.logs, 'pairwise': pair_res.logs, 'assembler': asm_res.logs}
                bundle = self._save_diagnostics(workdir, 'assemble_after_pair_fail', diagnostics)
                return JobResult(success=False, diagnostics_bundle=bundle)

        # both failed - save diagnostics bundle
        diagnostics = {'extractor': extract_res.logs, 'batch': batch_res.logs, 'pairwise': pair_res.logs}
        bundle = self._save_diagnostics(workdir, 'interp_failed', diagnostics)
        write_progress('failed', {'bundle': bundle})
        return JobResult(success=False, diagnostics_bundle=bundle)
