from dataclasses import dataclass
from typing import Optional
import os
import glob
import shlex

from ..utils.shell import run_cmd


@dataclass
class ExtractResult:
    frames_count: int
    width: Optional[int] = None
    height: Optional[int] = None
    pad_w: Optional[int] = None
    pad_h: Optional[int] = None
    audio_path: Optional[str] = None
    logs: Optional[str] = None


class FrameExtractor:
    def extract_frames(self, input_path: str, dest_dir: str, pad_to: Optional[int] = 32) -> ExtractResult:
        """Extract frames (PNG) and audio from `input_path` into `dest_dir`.
        Returns ExtractResult with discovered sizes and counts.

        Behavior:
        - probe width/height via ffprobe
        - compute pad to next multiple of `pad_to` (if probe available)
        - run ffmpeg to export PNG frames (padded if possible)
        - if PNG extraction yields zero frames, try MJPEG JPEG extraction as fallback
        - extract audio track to audio.aac if present
        """
        os.makedirs(dest_dir, exist_ok=True)
        input_dir = os.path.join(dest_dir, "input")
        output_dir = os.path.join(dest_dir, "output")
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        logs = []
        # Probe width/height
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            input_path,
        ]
        rc, out, err = run_cmd(probe_cmd)
        logs.append(f"probe rc={rc} out={out.strip()} err={err.strip()}")
        width = None
        height = None
        pad_w = None
        pad_h = None
        if rc == 0 and out.strip():
            try:
                parts = out.strip().split('x')
                width = int(parts[0])
                height = int(parts[1])
                if pad_to and pad_to > 0:
                    pad_w = ((width + pad_to - 1) // pad_to) * pad_to
                    pad_h = ((height + pad_to - 1) // pad_to) * pad_to
            except Exception as e:
                logs.append(f"probe parse error: {e}")

        # Build pad filter if available
        vf = None
        if pad_w and pad_h:
            # Use pad=ow:oh with explicit target values
            vf = f"pad={pad_w}:{pad_h}"

        # Try PNG extraction
        png_pattern = os.path.join(input_dir, "frame_%06d.png")
        if vf:
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                input_path,
                "-map",
                "0:v:0",
                "-vsync",
                "0",
                "-start_number",
                "1",
                "-vf",
                vf,
                "-f",
                "image2",
                "-vcodec",
                "png",
                png_pattern,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "info",
                "-i",
                input_path,
                "-map",
                "0:v:0",
                "-vsync",
                "0",
                "-start_number",
                "1",
                "-f",
                "image2",
                "-vcodec",
                "png",
                png_pattern,
            ]
        rc, out, err = run_cmd(cmd)
        logs.append(f"png_extract rc={rc} stdout={out.strip()[:200]} stderr={err.strip()[:200]}")

        # Count produced frames (png or jpg)
        pngs = sorted(glob.glob(os.path.join(input_dir, "*.png")))
        count = len(pngs)
        # If zero, try MJPEG extraction to JPG to avoid png decoder issues
        if count == 0:
            logs.append("PNG extraction produced 0 frames, trying JPEG (mjpeg) fallback")
            # remove any leftover
            for p in glob.glob(os.path.join(input_dir, "*")):
                try:
                    os.remove(p)
                except Exception:
                    pass
            if vf:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-i",
                    input_path,
                    "-map",
                    "0:v:0",
                    "-vsync",
                    "0",
                    "-start_number",
                    "1",
                    "-vf",
                    vf,
                    "-pix_fmt",
                    "yuvj420p",
                    "-f",
                    "image2",
                    "-vcodec",
                    "mjpeg",
                    os.path.join(input_dir, "frame_%06d.jpg"),
                ]
            else:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    "-i",
                    input_path,
                    "-map",
                    "0:v:0",
                    "-vsync",
                    "0",
                    "-start_number",
                    "1",
                    "-pix_fmt",
                    "yuvj420p",
                    "-f",
                    "image2",
                    "-vcodec",
                    "mjpeg",
                    os.path.join(input_dir, "frame_%06d.jpg"),
                ]
            rc2, out2, err2 = run_cmd(cmd)
            logs.append(f"jpg_extract rc={rc2} stdout={out2.strip()[:200]} stderr={err2.strip()[:200]}")
            jpgs = sorted(glob.glob(os.path.join(input_dir, "*.jpg")))
            count = len(jpgs)
        # Extract audio if present
        audio_path = os.path.join(dest_dir, "audio.aac")
        cmd_audio = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "copy",
            audio_path,
        ]
        rc_a, out_a, err_a = run_cmd(cmd_audio)
        logs.append(f"audio_extract rc={rc_a} stdout={out_a.strip()[:200]} stderr={err_a.strip()[:200]}")
        if rc_a != 0 or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
            # remove zero-size audio if created
            try:
                if os.path.exists(audio_path) and os.path.getsize(audio_path) == 0:
                    os.remove(audio_path)
            except Exception:
                pass
            audio_path_result = None
        else:
            audio_path_result = audio_path

        return ExtractResult(
            frames_count=count,
            width=width,
            height=height,
            pad_w=pad_w,
            pad_h=pad_h,
            audio_path=audio_path_result,
            logs='\n'.join(logs),
        )
