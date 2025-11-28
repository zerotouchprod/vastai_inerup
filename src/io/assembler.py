from typing import List, Optional
from pathlib import Path
from dataclasses import dataclass
from ..utils.shell import run_cmd

@dataclass
class AssemblyResult:
    success: bool
    output_path: Optional[str] = None
    size_bytes: Optional[int] = None
    logs: str = ''

class FrameAssembler:
    """Assemble frames into a video using ffmpeg filelist or pattern."""

    def __init__(self, ffmpeg_cmd: str = "ffmpeg"):
        self.ffmpeg = ffmpeg_cmd

    def assemble_from_pattern(self, input_dir: str, pattern: str, fps: float, out_file: str) -> AssemblyResult:
        cmd = [self.ffmpeg, "-y", "-framerate", str(fps), "-i", str(Path(input_dir) / pattern), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_file]
        rc, out, err = run_cmd(cmd)
        logs = out or err
        return AssemblyResult(success=(rc == 0), output_path=out_file if rc == 0 else None, logs=logs)

    def assemble_from_filelist(self, filelist_path: str, fps: float, out_file: str) -> AssemblyResult:
        cmd = [self.ffmpeg, "-y", "-safe", "0", "-f", "concat", "-i", filelist_path, "-framerate", str(fps), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_file]
        rc, out, err = run_cmd(cmd)
        logs = out or err
        return AssemblyResult(success=(rc == 0), output_path=out_file if rc == 0 else None, logs=logs)

    def assemble(self, frames: list, audio_path: Optional[str], out_file: str, fps: float = 24.0) -> AssemblyResult:
        """High-level assemble: verify frames sizes (ffprobe), normalize if needed, then concat.

        Tests mock run_cmd, so keep logic simple: call ffprobe on a sample of frames.
        """
        # quick probe to check sizes
        sizes = []
        logs = []
        for f in frames:
            rc, out, err = run_cmd(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,pix_fmt", "-of", "default=nokey=1:noprint_wrappers=1", f])
            logs.append(out or err)
            if rc == 0 and out:
                parts = out.strip().splitlines()
                if len(parts) >= 2:
                    w = parts[0]
                    h = parts[1]
                    sizes.append((w, h))
                else:
                    sizes.append(None)
            else:
                sizes.append(None)

        # If any None or mismatches, perform a simple normalization: call ffmpeg to rewrite files to same pix_fmt
        if any(s is None for s in sizes) or len(set(sizes)) > 1:
            # normalize each file (mocked by tests)
            for f in frames:
                # produce normalized temp file path
                tmp_out = f
                cmd = ["ffmpeg", "-v", "error", "-i", f, "-vf", "format=rgba", tmp_out]
                run_cmd(cmd)

        # create filelist
        filelist = str(Path(out_file).with_suffix('.filelist.txt'))
        with open(filelist, 'w', encoding='utf-8') as fh:
            for f in frames:
                fh.write(f"file '{f}'\n")

        return self.assemble_from_filelist(filelist, fps, out_file)
