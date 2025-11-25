#!/usr/bin/env python3
"""
Простой дешёвый пайплайн апскейлинга и интерполяции видео.
Поддерживает автоматический поиск ncnn-vulkan бинарников (`realesrgan-ncnn-vulkan`, `rife-ncnn-vulkan`) и переключение на них.
Также поддерживает режимы: только апскейл, только интерполяция, оба; и стратегию "low-res first" (interp-then-upscale) для экономии памяти.

Фоллбэк: если ncnn-бинарники отсутствуют или их вызов падает — используется ffmpeg-реализация.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional
from datetime import datetime

# Final marker used by remote monitoring to detect full successful completion
FINAL_PIPELINE_MARKER = "=== VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY ==="


def ts():
    return datetime.now().strftime('%H:%M:%S')


def log_stage(stage: str, infile: str):
    try:
        name = infile if infile else '<unknown>'
        print(f"[{ts()}] 🎬 {stage}: {name}", flush=True)
    except Exception:
        print(f"{stage}: {infile}", flush=True)


def check_command(cmd_name: str) -> bool:
    return shutil.which(cmd_name) is not None


def run(cmd, capture_output: bool = False):
    print("RUN:", " ".join(cmd))
    return subprocess.run(cmd, check=True, stdout=(subprocess.PIPE if capture_output else None), stderr=subprocess.STDOUT)


def get_avg_fps(path: str) -> float:
    if not check_command("ffprobe"):
        raise RuntimeError("ffprobe not found in PATH; ffmpeg suite is required")
    cmd = [
        "ffprobe", "-v", "0", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    s = res.stdout.decode().strip()
    if not s:
        raise RuntimeError("Could not determine video fps from ffprobe")
    if "/" in s:
        num, den = s.split("/")
        try:
            return float(num) / float(den)
        except Exception:
            return float(s)
    return float(s)


def get_duration_seconds(path: str) -> float:
    """Return video duration in seconds using ffprobe, or 0.0 on failure."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ]
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        s = res.stdout.strip()
        if not s:
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def detect_ncnn_binaries():
    """Return dict with availability of common ncnn-vulkan binaries."""
    bins = {
        "realesrgan": shutil.which("realesrgan-ncnn-vulkan") or shutil.which("realesrgan-ncnn") or shutil.which("realesrgan"),
        "rife": shutil.which("rife-ncnn-vulkan") or shutil.which("rife-ncnn") or shutil.which("rife"),
    }
    return bins


def do_upscale_ffmpeg(infile: str, outpath: str, scale_expr: str):
    cmd_up = [
        "ffmpeg", "-y", "-i", infile,
        "-vf", f"scale={scale_expr}:flags=lanczos",
        "-pix_fmt", "rgb24",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        outpath
    ]
    run(cmd_up)


def do_interpolate_ffmpeg(infile: str, outpath: str, target_fps: int):
    cmd_interp = [
        "ffmpeg", "-y", "-i", infile,
        "-vf", f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
        "-pix_fmt", "rgb24",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        outpath
    ]
    run(cmd_interp)


def try_run_realesrgan_ncnn(infile: str, outpath: str, scale: int) -> bool:
    """
    Try to run realesrgan-ncnn-vulkan on a file. Return True on success.
    We attempt a conservative command; if it fails, we return False and let caller fallback.
    Note: flags for reale srgan-ncnn-vulkan can vary across builds. We try a common form.
    """
    bin_path = shutil.which("realesrgan-ncnn-vulkan") or shutil.which("realesrgan-ncnn") or shutil.which("realesrgan")
    if not bin_path:
        return False
    try:
        # Try direct video input first (some builds support it)
        cmd = [bin_path, "-i", infile, "-o", outpath, "-s", str(scale)]
        try:
            run(cmd)
            return True
        except subprocess.CalledProcessError as e:
            print(f"realesrgan-ncnn invocation failed (direct video mode): {e}")
            # continue to frame-based fallback
        # Fallback: process frames (extract -> process -> assemble)
        try:
            with tempfile.TemporaryDirectory(prefix="realesrgan_frames_") as frd:
                frames_in = os.path.join(frd, "in_%06d.png")
                frames_out_dir = os.path.join(frd, "out_frames")
                os.makedirs(frames_out_dir, exist_ok=True)
                # extract frames
                run(["ffmpeg", "-y", "-i", infile, "-pix_fmt", "rgb24", frames_in])
                # process each frame via realesrgan (image mode)
                for fname in sorted(os.listdir(frd)):
                    if not fname.startswith("in_"):
                        continue
                    inpath = os.path.join(frd, fname)
                    outname = fname.replace("in_", "out_")
                    outpath_img = os.path.join(frames_out_dir, outname)
                    try:
                        # capture output to show in logs if fails
                        print(f"Running: {bin_path} -i {inpath} -o {outpath_img} -s {scale}")
                        res = subprocess.run([bin_path, "-i", inpath, "-o", outpath_img, "-s", str(scale)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        print(res.stdout)
                        if res.stderr:
                            print(res.stderr)
                    except subprocess.CalledProcessError as e:
                        print(f"realesrgan-ncnn image-mode failed for {inpath}: returncode={e.returncode}")
                        try:
                            print(e.stdout)
                        except Exception:
                            pass
                        try:
                            print(e.stderr)
                        except Exception:
                            pass
                        return False
                # assemble back to video
                run(["ffmpeg", "-y", "-framerate", "$(ffprobe -v 0 -select_streams v:0 -show_entries stream=avg_frame_rate -of default=noprint_wrappers=1:nokey=1 \"$infile\")", "-i", os.path.join(frames_out_dir, "out_%06d.png"), "-c:v", "libx264", "-crf", "18", "-preset", "medium", outpath])
                return True
        except Exception as e:
            print(f"realesrgan-ncnn frame-mode exception: {e}")
            return False
    except Exception as e:
        print(f"realesrgan-ncnn unexpected error: {e}")
        return False


def try_run_rife_ncnn(infile: str, outpath: str, factor: int) -> bool:
    bin_path = shutil.which("rife-ncnn-vulkan") or shutil.which("rife-ncnn") or shutil.which("rife")
    if not bin_path:
        return False
    try:
        # Common invocation (may vary)
        cmd = [bin_path, "-i", infile, "-o", outpath, "-n", str(factor)]
        run(cmd)
        return True
    except subprocess.CalledProcessError:
        # fallback to frame-based processing (expensive) — try and fail gracefully
        try:
            with tempfile.TemporaryDirectory(prefix="rife_frames_") as frd:
                frames_in = os.path.join(frd, "in_%06d.png")
                frames_out_dir = os.path.join(frd, "out_frames")
                os.makedirs(frames_out_dir, exist_ok=True)
                run(["ffmpeg", "-y", "-i", infile, frames_in])
                # Here we'd need to do pairwise frame interpolation to increase FPS; too complex to implement robustly here.
                # Return False to trigger ffmpeg fallback.
                return False
        except Exception:
            return False


def try_run_realesrgan_pytorch_wrapper(infile: str, outpath: str, scale: int) -> bool:
    """Try to run local wrapper script for Real-ESRGAN PyTorch implementation."""
    wrapper = "/workspace/project/run_realesrgan_pytorch.sh"
    log_stage("Invoking PyTorch Real-ESRGAN wrapper", infile)
    if not os.path.isfile(wrapper) or not os.access(wrapper, os.X_OK):
        return False
    try:
        # Check input file
        if not os.path.exists(infile):
            print(f"ERROR: Input file not found: {infile}", flush=True)
            return False

        file_size = os.path.getsize(infile) / (1024*1024)  # MB
        print(f"Input file: {infile} ({file_size:.1f} MB)", flush=True)

        # Quick GPU check
        try:
            import torch
            if torch.cuda.is_available():
                print(f"✓ GPU available: {torch.cuda.get_device_name(0)}", flush=True)
            else:
                print("⚠ WARNING: GPU not available, Real-ESRGAN will be slow!", flush=True)
        except:
            pass

        # Run without capturing output for real-time streaming
        print(f"Invoking PyTorch Real-ESRGAN wrapper: {wrapper} {infile} {outpath} {scale}", flush=True)
        print(f"⏱️  Starting Real-ESRGAN at {__import__('datetime').datetime.now().strftime('%H:%M:%S')}", flush=True)

        # Use Popen for real-time output and timeout support
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("Real-ESRGAN wrapper timeout (30 minutes)")

        # Set timeout (30 minutes should be enough for most videos)
        TIMEOUT_SECONDS = 1800  # 30 minutes
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(TIMEOUT_SECONDS)

        try:
            # Don't capture output - let it stream directly
            res = subprocess.run([wrapper, infile, outpath, str(scale)], check=True, timeout=TIMEOUT_SECONDS)
            signal.alarm(0)  # Cancel timeout
            print(f"✓ Real-ESRGAN completed at {__import__('datetime').datetime.now().strftime('%H:%M:%S')}", flush=True)
            return True
        except subprocess.TimeoutExpired:
            signal.alarm(0)
            print(f"ERROR: Real-ESRGAN wrapper timeout after {TIMEOUT_SECONDS//60} minutes", flush=True)
            return False
        except subprocess.CalledProcessError as e:
            signal.alarm(0)
            print(f"PyTorch Real-ESRGAN wrapper failed: returncode={e.returncode}", flush=True)
            return False
    except Exception as e:
        print(f"PyTorch Real-ESRGAN wrapper exception: {e}", flush=True)
        return False


def try_run_rife_pytorch_wrapper(infile: str, outpath: str, factor: int) -> bool:
    """Try to run local wrapper script for RIFE PyTorch implementation."""
    wrapper = "/workspace/project/run_rife_pytorch.sh"
    log_stage("Invoking PyTorch RIFE wrapper", infile)
    if not os.path.isfile(wrapper) or not os.access(wrapper, os.X_OK):
        return False
    try:
        # Compute and print estimated total frames and ETA ranges before starting
        try:
            duration = get_duration_seconds(infile)
            orig_fps = get_avg_fps(infile)
            num_input_frames = int(round(duration * orig_fps)) if duration and orig_fps else None
            pairs = max(0, (num_input_frames - 1) if num_input_frames else 0)
            # total output frames: originals + pairs*(factor-1)
            total_output_frames = (num_input_frames + pairs * (factor - 1)) if num_input_frames is not None else None
            print(f"Invoking PyTorch RIFE wrapper: {wrapper} {infile} {outpath} {factor}", flush=True)
            print(f"⏱️  Starting RIFE at {__import__('datetime').datetime.now().strftime('%H:%M:%S')}", flush=True)
            if num_input_frames:
                print(f"📌 Detected: duration={duration:.2f}s, original fps={orig_fps:.3f} => input frames≈{num_input_frames}")
                print(f"📌 Frame pairs to process: {pairs} | estimated total output frames: {total_output_frames}")
                # ETA heuristics (seconds per pair)
                speeds = {'fast': 0.2, 'med': 0.7, 'slow': 5.0}  # seconds per pair
                # prefer med if CUDA available
                try:
                    import torch
                    has_cuda = getattr(torch, 'cuda', None) and torch.cuda.is_available()
                except Exception:
                    has_cuda = False
                recommended = 'med' if has_cuda else 'slow'
                def fmt_sec(s):
                    if s is None:
                        return 'unknown'
                    s = int(round(s))
                    h = s // 3600
                    m = (s % 3600) // 60
                    sec = s % 60
                    if h:
                        return f"{h:d}:{m:02d}:{sec:02d}"
                    return f"{m:02d}:{sec:02d}"
                for k, sec_per_pair in speeds.items():
                    eta = pairs * sec_per_pair
                    print(f"   ETA ({k}): {fmt_sec(eta)} (assuming {1/sec_per_pair:.1f} pairs/sec)")
                print(f"   Recommended estimate: {recommended}")
        except Exception as _e:
            print(f"Could not estimate total frames/ETA: {_e}", flush=True)

        # Use timeout - RIFE can take VERY long for high interpolation factors
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("RIFE wrapper timeout (30 minutes)")

        # Set timeout (30 minutes for high factor interpolation like 120fps)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(1800)  # 30 minutes timeout (was 600 = 10 min)

        try:
            # Don't capture output - let it stream directly
            res = subprocess.run([wrapper, infile, outpath, str(factor)], check=True, timeout=1800)
            signal.alarm(0)  # Cancel timeout
            print(f"✓ RIFE completed at {__import__('datetime').datetime.now().strftime('%H:%M:%S')}", flush=True)
            return True
        except subprocess.TimeoutExpired:
            signal.alarm(0)
            print(f"ERROR: RIFE wrapper timeout after 30 minutes", flush=True)
            return False
        except subprocess.CalledProcessError as e:
            signal.alarm(0)
            print(f"PyTorch RIFE wrapper failed: returncode={e.returncode}", flush=True)
            return False
    except Exception as e:
        print(f"PyTorch RIFE wrapper exception: {e}", flush=True)
        return False


def do_upscale(infile: str, outpath: str, scale_expr: str, prefer: str = "auto", strict: bool = False):
    log_stage("Starting UPSCALE", infile)
    print(f"[pipeline.do_upscale] Called with: infile={infile}, outpath={outpath}, scale_expr={scale_expr}, prefer={prefer}, strict={strict}")
    # If user requested PyTorch backend, try local wrapper then fallback
    bins = detect_ncnn_binaries()

    # Infer scale_int for PyTorch/ncnn wrappers
    scale_int = None
    try:
        if "*" in scale_expr:
            left = scale_expr.split(":")[0]
            if "*" in left:
                scale_int = int(float(left.split("*")[1]))
    except Exception:
        pass
    if scale_int is None:
        scale_int = 4 if "3840" in scale_expr or "4k" in scale_expr.lower() else 2

    # In 'auto' mode, prefer PyTorch wrapper if it's present and torch.cuda is available
    if prefer == "auto":
        wrapper = "/workspace/project/run_realesrgan_pytorch.sh"
        try:
            if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
                try:
                    import torch
                    if getattr(torch, 'cuda', None) and torch.cuda.is_available():
                        log_stage("Attempting PyTorch Real-ESRGAN wrapper", infile)
                        print("Auto-detected PyTorch+CUDA and wrapper present; attempting PyTorch Real-ESRGAN wrapper")
                        try:
                            if try_run_realesrgan_pytorch_wrapper(infile, outpath, scale_int):
                                print("[SUCCESS] PyTorch Real-ESRGAN wrapper completed successfully")
                                return
                        except Exception as e:
                            print("Error while running PyTorch Real-ESRGAN wrapper:", e)
                            if strict:
                                raise RuntimeError(f"STRICT MODE: PyTorch Real-ESRGAN wrapper error: {e}")
                    else:
                        if strict:
                            raise RuntimeError("STRICT MODE: PyTorch CUDA not available, but GPU processing is required (--strict mode)")
                except ImportError as e:
                    if strict:
                        raise RuntimeError(f"STRICT MODE: torch import failed: {e}")
        except RuntimeError:
            raise  # re-raise strict mode errors
        except Exception:
            pass
    elif prefer == "pytorch":
        # attempt pytorch wrapper explicitly requested
        print("Attempting PyTorch Real-ESRGAN wrapper (explicitly requested via --prefer pytorch)...")
        wrapper = "/workspace/project/run_realesrgan_pytorch.sh"
        if not os.path.isfile(wrapper):
            msg = f"PyTorch Real-ESRGAN wrapper not found at {wrapper}"
            print(f"ERROR: {msg}")
            if strict:
                raise RuntimeError(f"STRICT MODE: {msg}")
        elif not os.access(wrapper, os.X_OK):
            msg = f"PyTorch Real-ESRGAN wrapper not executable: {wrapper}"
            print(f"ERROR: {msg}")
            if strict:
                raise RuntimeError(f"STRICT MODE: {msg}")
        else:
            try:
                if try_run_realesrgan_pytorch_wrapper(infile, outpath, scale_int):
                    print("[SUCCESS] PyTorch Real-ESRGAN wrapper completed successfully")
                    return
                print("PyTorch Real-ESRGAN wrapper failed")
                if strict:
                    raise RuntimeError("STRICT MODE: PyTorch Real-ESRGAN wrapper failed, but GPU processing is required")
            except Exception as e:
                print("Error while running PyTorch Real-ESRGAN wrapper:", e)
                if strict:
                    raise RuntimeError(f"STRICT MODE: PyTorch Real-ESRGAN wrapper error: {e}")

    # If prefer is auto or ncnn allowed, try ncnn
    if prefer == "auto" and bins.get("realesrgan"):
        log_stage("Attempting realesrgan-ncnn (NCNN)", infile)
        print("Detected realesrgan-ncnn-vulkan available; attempting to use it (scale", scale_int, ")")
        try:
            success = try_run_realesrgan_ncnn(infile, outpath, scale_int)
            if success:
                print("[SUCCESS] realesrgan-ncnn-vulkan completed successfully")
                return
            print("realesrgan-ncnn-vulkan invocation failed")
            if strict:
                raise RuntimeError("STRICT MODE: realesrgan-ncnn-vulkan failed, but GPU processing is required")
        except RuntimeError:
            raise  # re-raise strict mode errors
        except Exception as e:
            print("realesrgan-ncnn-vulkan raised error:", e)
            if strict:
                raise RuntimeError(f"STRICT MODE: realesrgan-ncnn-vulkan error: {e}")

    # Reached fallback
    if strict:
        raise RuntimeError("STRICT MODE: No GPU backends (PyTorch/ncnn) available or succeeded, falling back to ffmpeg is not allowed in strict mode. Use --no-strict to allow CPU fallback.")

    log_stage("Fallback to ffmpeg (UPSCALE)", infile)
    print("[FALLBACK] Using ffmpeg CPU upscale (no GPU acceleration)")
    # fallback: ffmpeg
    do_upscale_ffmpeg(infile, outpath, scale_expr)


def do_interpolate(infile: str, outpath: str, target_fps: int, prefer: str = "auto", strict: bool = False):
    log_stage("Starting INTERPOLATION", infile)
    print(f"[pipeline.do_interpolate] Called with: infile={infile}, outpath={outpath}, target_fps={target_fps}, prefer={prefer}, strict={strict}")
    # If user requested PyTorch backend, try local wrapper then fallback
    bins = detect_ncnn_binaries()

    # Calculate interpolation factor
    factor = None
    try:
        orig = get_avg_fps(infile)
        factor = max(1, int(round(target_fps / max(1, orig))))
    except Exception:
        factor = 2

    # In 'auto' mode, prefer PyTorch wrapper if it's present and torch.cuda is available
    if prefer == "auto":
        wrapper = "/workspace/project/run_rife_pytorch.sh"
        try:
            if os.path.isfile(wrapper) and os.access(wrapper, os.X_OK):
                try:
                    import torch
                    if getattr(torch, 'cuda', None) and torch.cuda.is_available():
                        log_stage("Attempting PyTorch RIFE wrapper", infile)
                        print("Auto-detected PyTorch+CUDA and RIFE wrapper present; attempting PyTorch RIFE wrapper")
                        try:
                            if try_run_rife_pytorch_wrapper(infile, outpath, factor):
                                print("[SUCCESS] PyTorch RIFE wrapper completed successfully")
                                return
                            print("PyTorch RIFE wrapper failed or not available")
                            if strict:
                                raise RuntimeError("STRICT MODE: PyTorch RIFE wrapper failed, но GPU processing is required")
                        except Exception as e:
                            print("Error while running PyTorch RIFE wrapper:", e)
                            if strict:
                                raise RuntimeError(f"STRICT MODE: PyTorch RIFE wrapper error: {e}")
                    else:
                        if strict:
                            raise RuntimeError("STRICT MODE: PyTorch CUDA not available, но GPU processing is required")
                except ImportError as e:
                    if strict:
                        raise RuntimeError(f"STRICT MODE: torch import failed: {e}")
        except RuntimeError:
            raise  # re-raise strict mode errors
        except Exception:
            pass
    elif prefer == "pytorch":
        print("Attempting PyTorch RIFE wrapper (explicitly requested via --prefer pytorch)...")
        wrapper = "/workspace/project/run_rife_pytorch.sh"
        if not os.path.isfile(wrapper):
            msg = f"PyTorch RIFE wrapper not found at {wrapper}"
            print(f"ERROR: {msg}")
            if strict:
                raise RuntimeError(f"STRICT MODE: {msg}")
        elif not os.access(wrapper, os.X_OK):
            msg = f"PyTorch RIFE wrapper not executable: {wrapper}"
            print(f"ERROR: {msg}")
            if strict:
                raise RuntimeError(f"STRICT MODE: {msg}")
        else:
            try:
                if try_run_rife_pytorch_wrapper(infile, outpath, factor):
                    print("[SUCCESS] PyTorch RIFE wrapper completed successfully")
                    return
                print("PyTorch RIFE wrapper failed")
                if strict:
                    raise RuntimeError("STRICT MODE: PyTorch RIFE wrapper failed, but GPU processing is required")
            except Exception as e:
                print("Error while running PyTorch RIFE wrapper:", e)
                if strict:
                    raise RuntimeError(f"STRICT MODE: PyTorch RIFE wrapper error: {e}")

    # Try ncnn if allowed
    if prefer in ("ncnn", "auto") and bins.get("rife") and factor and factor >= 2:
        log_stage("Attempting rife-ncnn (NCNN)", infile)
        print("Detected rife-ncnn-vulkan available; attempting to use it (factor", factor, ")")
        try:
            success = try_run_rife_ncnn(infile, outpath, factor)
            if success:
                print("[SUCCESS] rife-ncnn-vulkan completed успешно")
                return
            print("rife-ncnn-vulkan invocation failed")
            if strict:
                raise RuntimeError("STRICT MODE: rife-ncnn-vulkan failed, but GPU processing is required")
        except RuntimeError:
            raise  # re-raise strict mode errors
        except Exception as e:
            print("rife-ncnn-вулкан raised error:", e)
            if strict:
                raise RuntimeError(f"STRICT MODE: rife-ncnn-вулкан error: {e}")

    # Reached fallback
    if strict:
        raise RuntimeError("STRICT MODE: No GPU backends (PyTorch/ncnn) available or succeeded, falling back to ffmpeg is not allowed in strict mode. Use --no-strict to allow CPU fallback.")

    print("[FALLBACK] Using ffmpeg CPU interpolation (no GPU acceleration)")
    do_interpolate_ffmpeg(infile, outpath, target_fps)


def main():
    parser = argparse.ArgumentParser(description="Cheap upscale + interpolation pipeline using ffmpeg (with optional ncnn/pytorch acceleration)")
    parser.add_argument("--input", "-i", required=True, help="Input video file path")
    parser.add_argument("--output", "-o", required=True, help="Output directory")
    parser.add_argument("--scale", "-s", type=float, default=2.0, help="Upscale factor (default 2.0)")
    parser.add_argument("--target-res", "-t", type=str, default=None, help="Target resolution as WIDTHxHEIGHT (e.g. 3840x2160) or '4k' to upscale to 3840x2160. Preserves aspect ratio using -2 for height.")
    parser.add_argument("--interp-factor", "-f", type=float, default=2.0, help="Interpolation factor relative to original fps (e.g. 2.0 -> double FPS)")
    parser.add_argument("--target-fps", type=int, default=None, help="Target FPS (absolute). If set, overrides --interp-factor")
    parser.add_argument("--keep-tmp", action="store_true", help="Don't remove temporary files")
    parser.add_argument("--mode", choices=["upscale", "interp", "both"], default="both", help="Run only upscale, only interpolation, or both (default both)")
    parser.add_argument("--prefer", choices=["auto", "ncnn", "pytorch", "ffmpeg"], default="auto", help="Prefered backend: ncnn (ncnn-vulkan), pytorch (if installed), or ffmpeg (default ffmpeg). 'auto' tries ncnn then ffmpeg")
    parser.add_argument("--lowres-strategy", choices=["upscale-then-interp", "interp-then-upscale"], default="interp-then-upscale", help="Strategy for combined pipeline: interpolate at low-res then upscale (default, faster) or upscale first then interpolate (more memory)")
    parser.add_argument("--strict", action="store_true", default=False, help="Strict mode: fail if GPU backends (PyTorch/ncnn) are not available or fail. Use --strict to enable strict mode.")
    parser.add_argument("--no-strict", dest="strict", action="store_false", help="Allow fallback to CPU/ffmpeg if GPU backends fail")
    args = parser.parse_args()

    infile = os.path.abspath(args.input)
    outdir = os.path.abspath(args.output)
    os.makedirs(outdir, exist_ok=True)

    if not os.path.isfile(infile):
        print(f"Input file not found: {infile}")
        sys.exit(2)

    if not check_command("ffmpeg"):
        print("ffmpeg not found in PATH. Install ffmpeg before running this pipeline.")
        sys.exit(3)

    print("Input:", infile)
    print("Output dir:", outdir)
    print("Mode:", args.mode)
    print("Scale (multiplier):", args.scale)
    print("Target resolution:", args.target_res)
    print("Interp factor:", args.interp_factor)
    print("Target FPS:", args.target_fps)
    print("Prefer backend:", args.prefer)
    print("Low-res strategy:", args.lowres_strategy)

    bins = detect_ncnn_binaries()
    print("Detected ncnn binaries:", bins)

    with tempfile.TemporaryDirectory(prefix="vastai_pipeline_") as tmp:
        print("Using tmp dir:", tmp)
        try:
            # determine original fps
            orig_fps = get_avg_fps(infile)
            print(f"Detected original fps: {orig_fps:.3f}")

            # Compute scale expression
            if args.target_res:
                tr = args.target_res.strip().lower()
                if tr in ("4k", "2160p"):
                    width = 3840
                    scale_expr = f"{width}:-2"
                else:
                    try:
                        w, h = tr.split("x")
                        width = int(w); height = int(h)
                        scale_expr = f"{width}:{height}"
                    except Exception:
                        print("Invalid --target-res format. Use WIDTHxHEIGHT or '4k'.")
                        sys.exit(4)
            else:
                scale_expr = f"iw*{args.scale}:ih*{args.scale}"

            target_fps = args.target_fps if args.target_fps is not None else max(1, int(round(orig_fps * args.interp_factor)))

            # Branch by mode
            if args.mode == "upscale":
                up_out = os.path.join(outdir, "output_upscaled.mp4")
                do_upscale(infile, up_out, scale_expr, prefer=args.prefer, strict=args.strict)
                print("Upscale finished. Output:", up_out)
                # Final success marker for external monitor
                try:
                    print(FINAL_PIPELINE_MARKER)
                except Exception:
                    pass

                if args.keep_tmp:
                    shutil.copy(up_out, os.path.join(outdir, "tmp_upscaled.mp4"))
                return

            if args.mode == "interp":
                interp_out = os.path.join(outdir, "output_interpolated.mp4")
                do_interpolate(infile, interp_out, target_fps, prefer=args.prefer, strict=args.strict)
                print("Interpolation finished. Output:", interp_out)
                # Final success marker for external monitor
                try:
                    print(FINAL_PIPELINE_MARKER)
                except Exception:
                    pass

                if args.keep_tmp:
                    shutil.copy(interp_out, os.path.join(outdir, "tmp_interpolated.mp4"))
                return

            # mode == both
            # Two strategies: upscale-then-interp (default) OR interp-then-upscale (low-res first)
            if args.lowres_strategy == "interp-then-upscale":
                # 1) interpolate at original res -> tmp_interpolated
                tmp_inter = os.path.join(tmp, "interpolated.mp4")
                do_interpolate(infile, tmp_inter, target_fps, prefer=args.prefer, strict=args.strict)
                # 2) upscale the interpolated
                out_final = os.path.join(outdir, "output_interpolated_upscaled.mp4")
                do_upscale(tmp_inter, out_final, scale_expr, prefer=args.prefer, strict=args.strict)
                print("Pipeline finished (interp then upscale). Output file:", out_final)
                # Final success marker for external monitor
                try:
                    print(FINAL_PIPELINE_MARKER)
                except Exception:
                    pass
                if args.keep_tmp:
                    keep_path = os.path.join(outdir, "tmp_kept")
                    os.makedirs(keep_path, exist_ok=True)
                    shutil.copy(tmp_inter, os.path.join(keep_path, "interpolated.mp4"))
                    shutil.copy(out_final, os.path.join(keep_path, "final.mp4"))
                return
            else:
                # upscale then interpolate
                upscaled = os.path.join(tmp, "upscaled.mp4")
                do_upscale(infile, upscaled, scale_expr, prefer=args.prefer, strict=args.strict)

                # DEBUG: Check if upscaled file was created
                print(f"DEBUG: Upscale complete. Checking for output file: {upscaled}")
                print(f"DEBUG: File exists: {os.path.exists(upscaled)}")
                print(f"DEBUG: Is file: {os.path.isfile(upscaled)}")
                if os.path.exists(upscaled):
                    print(f"DEBUG: File size: {os.path.getsize(upscaled)} bytes")
                print(f"DEBUG: Contents of tmp directory: {os.listdir(tmp)}")

                output_file = os.path.join(outdir, "output_interpolated.mp4")
                do_interpolate(upscaled, output_file, target_fps, prefer=args.prefer, strict=args.strict)
                print("Pipeline finished (upscale then interp). Output file:", output_file)
                # Final success marker for external monitor
                try:
                    print(FINAL_PIPELINE_MARKER)
                except Exception:
                    pass
                if args.keep_tmp:
                    keep_path = os.path.join(outdir, "tmp_kept")
                    print("Keeping tmp dir ->", keep_path)
                    shutil.copytree(tmp, keep_path)
                return

        except subprocess.CalledProcessError as e:
            print("Command failed:", e)
            sys.exit(10)


if __name__ == "__main__":
    main()
