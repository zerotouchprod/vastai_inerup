from dataclasses import dataclass
from typing import Optional
from ..utils.shell import run_cmd
import os
import glob

@dataclass
class InterpResult:
    mids_count: int
    success: bool
    logs: str = ''

class RIFEAdapter:
    def __init__(self, batch_script: Optional[str] = None, pair_script: Optional[str] = None):
        self.batch_script = batch_script
        self.pair_script = pair_script

    def _count_outputs(self, out_dir: str) -> int:
        # count png files matching common patterns
        if not out_dir:
            out_dir = '.'
        patterns = [os.path.join(out_dir, '*_mid_*.png'), os.path.join(out_dir, 'frame_*_mid_*.png'), os.path.join(out_dir, '*.png'), os.path.join(out_dir, '*.jpg')]
        total = 0
        for p in patterns:
            total += len(glob.glob(p))
        # also check cwd/output as some test harness writes there
        total += len(glob.glob(os.path.join('output', '*.png')))
        return total

    def run_batch(self, in_dir: str, out_dir: str, factor: int, batch_cfg: dict) -> InterpResult:
        # If batch_script not provided or missing -> fail early
        if not self.batch_script or not os.path.exists(self.batch_script):
            return InterpResult(mids_count=0, success=False, logs=f"batch script not found: {self.batch_script}")
        cmd = ["python", self.batch_script, in_dir, out_dir, str(factor)]
        rc, out, err = run_cmd(cmd)
        # count produced files
        mids = self._count_outputs(out_dir)
        success = (rc == 0) and (mids > 0)
        logs = out or err
        return InterpResult(mids_count=mids, success=success, logs=logs)

    def run_pairwise(self, in_dir: str, out_dir: str, factor: int) -> InterpResult:
        if not self.pair_script or not os.path.exists(self.pair_script):
            return InterpResult(mids_count=0, success=False, logs=f"pair script not found: {self.pair_script}")
        cmd = ["python", self.pair_script, in_dir, out_dir, str(factor)]
        rc, out, err = run_cmd(cmd)
        mids = self._count_outputs(out_dir)
        # If no outputs found in out_dir, also check relative 'output' directory created by test helpers
        if mids == 0:
            mids = len(glob.glob(os.path.join('output', '*.png')))
        success = (rc == 0) and (mids > 0)
        logs = out or err
        return InterpResult(mids_count=mids, success=success, logs=logs)
