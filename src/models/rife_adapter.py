from dataclasses import dataclass
from typing import Optional, List
import os
import glob
import math
import shutil

from ..utils.shell import run_cmd


@dataclass
class InterpResult:
    mids_count: int
    output_pattern: Optional[str] = None
    success: bool = False
    logs: Optional[str] = None


class IInterpolator:
    def run_pairwise(self, in_dir: str, out_dir: str, factor: int) -> InterpResult:
        raise NotImplementedError

    def run_batch(self, in_dir: str, out_dir: str, factor: int, batch_cfg: dict) -> InterpResult:
        raise NotImplementedError


class RIFEAdapter(IInterpolator):
    """Adapter that invokes external RIFE scripts: batch_rife.py or inference_img.py

    It uses run_cmd helper to call ffmpeg/py scripts and inspects output directory for generated mids.
    """

    def __init__(self, batch_script: str = "/workspace/project/batch_rife.py", pair_script: str = "/workspace/project/external/RIFE/inference_img.py"):
        self.batch_script = batch_script
        self.pair_script = pair_script

    def _count_mids(self, out_dir: str) -> int:
        # count any pngs in output dir
        pngs = glob.glob(os.path.join(out_dir, "*.png"))
        return len(pngs)

    def run_batch(self, in_dir: str, out_dir: str, factor: int, batch_cfg: dict) -> InterpResult:
        logs = []
        if not os.path.isdir(in_dir):
            return InterpResult(mids_count=0, success=False, logs=f"input dir missing: {in_dir}")
        os.makedirs(out_dir, exist_ok=True)
        if os.path.isfile(self.batch_script):
            cmd = ["python3", self.batch_script, in_dir, out_dir, str(factor)]
            # append batch_cfg args (simple key/value)
            for k, v in (batch_cfg or {}).items():
                cmd.append(f"--{k}")
                if v is not None:
                    cmd.append(str(v))
            rc, out, err = run_cmd(cmd)
            logs.append(f"batch rc={rc}")
            logs.append(out)
            logs.append(err)
            mids = self._count_mids(out_dir)
            success = (rc == 0 and mids > 0)
            return InterpResult(mids_count=mids, output_pattern=os.path.join(out_dir, "*.png"), success=success, logs='\n'.join(logs))
        else:
            logs.append(f"batch script not found: {self.batch_script}")
            # return failure so caller can fallback to per-pair
            return InterpResult(mids_count=0, success=False, logs='\n'.join(logs))

    def run_pairwise(self, in_dir: str, out_dir: str, factor: int) -> InterpResult:
        logs: List[str] = []
        if not os.path.isdir(in_dir):
            return InterpResult(mids_count=0, success=False, logs=f"input dir missing: {in_dir}")
        os.makedirs(out_dir, exist_ok=True)
        # find frames sorted
        frames = sorted([p for p in glob.glob(os.path.join(in_dir, "*")) if os.path.isfile(p)])
        if len(frames) < 2:
            return InterpResult(mids_count=0, success=False, logs="not enough frames")
        mids = 0
        # determine exp param: use factor->exp heuristic: if factor>1, exp = int(math.log2(factor)) or 1
        try:
            exp = max(1, int(math.log2(factor))) if factor > 1 else 1
        except Exception:
            exp = 1
        for i in range(len(frames) - 1):
            a = frames[i]
            b = frames[i + 1]
            # run inference_img.py --img a b --exp <exp>
            if os.path.isfile(self.pair_script):
                cmd = ["python3", self.pair_script, "--img", a, b, "--exp", str(exp)]
                rc, out, err = run_cmd(cmd)
                logs.append(f"pair {i+1} rc={rc}")
                logs.append(out)
                logs.append(err)
                # inference_img writes output/img*.png or output/img1.png; look for any new pngs in out_dir
                # Move results from current working dir (inference_img writes ./output) if present
                possible = os.path.join(os.getcwd(), "output")
                if os.path.isdir(possible):
                    # move produced imgs into out_dir
                    for prod in sorted(glob.glob(os.path.join(possible, "*.png"))):
                        dest = os.path.join(out_dir, os.path.basename(prod))
                        try:
                            os.replace(prod, dest)
                        except Exception:
                            try:
                                shutil.copy(prod, dest)
                            except Exception:
                                pass
                # count mids now
                mids = self._count_mids(out_dir)
            else:
                logs.append(f"pair script not found: {self.pair_script}")
                return InterpResult(mids_count=0, success=False, logs='\n'.join(logs))
        success = mids > 0
        return InterpResult(mids_count=mids, output_pattern=os.path.join(out_dir, "*.png"), success=success, logs='\n'.join(logs))


# Keep Noop for compatibility
class NoopRIFE(IInterpolator):
    def run_pairwise(self, in_dir: str, out_dir: str, factor: int) -> InterpResult:
        return InterpResult(mids_count=0, success=True)

    def run_batch(self, in_dir: str, out_dir: str, factor: int, batch_cfg: dict) -> InterpResult:
        return InterpResult(mids_count=0, success=True)
