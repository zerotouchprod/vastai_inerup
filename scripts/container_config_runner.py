#!/usr/bin/env python3
"""
container_config_runner.py

Runs inside Docker container on Vast.ai.
Reads config.yaml from Git repo, downloads input, processes video, uploads output.

This allows updating processing parameters via Git without recreating instance!

Usage:
    python3 /workspace/project/scripts/container_config_runner.py /workspace/project/config.yaml
"""
import os
import sys
import yaml
import subprocess
from pathlib import Path
from datetime import datetime

# Final marker printed when container finished all work (used by external monitor to auto-stop instances)
FINAL_PIPELINE_MARKER = "=== VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY ==="

# Load .env file manually if present
# env_path = Path('/workspace/project/.env')
# if env_path.exists():
#     with open(env_path, 'r') as f:
#         for line in f:
#             line = line.strip()
#             if '=' in line and not line.startswith('#'):
#                 if line.startswith('export '):
#                     line = line[7:]  # Remove 'export '
#                 key, value = line.split('=', 1)
#                 key = key.strip()
#                 value = value.strip()
#                 os.environ[key] = value


def ts():
    """Get timestamp string for logging"""
    return datetime.now().strftime('%H:%M:%S')


def log_stage(stage: str, item: str = ''):
    try:
        name = item or '<unknown>'
        print(f"[{ts()}] 🎬 {stage}: {name}", flush=True)
    except Exception:
        print(f"{stage}: {item}", flush=True)


def estimate_processing_time(input_path: str, mode: str, scale: int, target_fps: int, current_fps: float = 24.0) -> dict:
    """Estimate processing time based on video characteristics and settings"""

    # Get video duration and frame count
    try:
        # Use ffprobe to get video info
        cmd = [
            'ffprobe', '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,nb_frames,duration',
            '-of', 'csv=p=0',
            input_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        parts = result.stdout.strip().split(',')

        # Parse fields safely
        width = int(parts[0]) if len(parts) > 0 and parts[0] and parts[0] != 'N/A' else 640
        height = int(parts[1]) if len(parts) > 1 and parts[1] and parts[1] != 'N/A' else 480
        fps_str = parts[2] if len(parts) > 2 and parts[2] else "24/1"
        nb_frames_str = parts[3] if len(parts) > 3 else ""
        duration_str = parts[4] if len(parts) > 4 else ""

        # Parse FPS (e.g., "24000/1001" or "24/1")
        if '/' in fps_str:
            num, den = fps_str.split('/')
            current_fps = float(num) / float(den)
        else:
            current_fps = float(fps_str) if fps_str else 24.0

        # Parse nb_frames (may be N/A or missing)
        if nb_frames_str and nb_frames_str != 'N/A':
            try:
                nb_frames = int(float(nb_frames_str))  # Convert float to int if needed
            except ValueError:
                nb_frames = 0
        else:
            nb_frames = 0

        # Parse duration (may be float)
        if duration_str and duration_str != 'N/A':
            try:
                duration = float(duration_str)
            except ValueError:
                duration = 0
        else:
            duration = 0

        # Calculate nb_frames from duration if not available
        if nb_frames == 0 and duration > 0:
            nb_frames = int(duration * current_fps)

        # Calculate duration from nb_frames if not available
        if duration == 0 and nb_frames > 0:
            duration = nb_frames / current_fps

    except Exception as e:
        # Fallback values
        width, height = 640, 480
        nb_frames = 145  # ~6 sec at 24fps
        duration = 6.0
        current_fps = 24.0
        print(f"⚠️  Could not detect video info, using defaults: {e}")

    # Calculate pixel count
    input_pixels = width * height

    # Calculate frame multiplier for interpolation
    interp_factor = target_fps / current_fps

    # Determine output dimensions and frames based on mode
    output_width = width * scale if mode in ('upscale', 'both') else width
    output_height = height * scale if mode in ('upscale', 'both') else height
    output_frames = int(nb_frames * interp_factor) if mode in ('interp', 'interpolate', 'both') else nb_frames
    output_fps = target_fps if mode in ('interp', 'interpolate', 'both') else current_fps
    output_pixels = output_width * output_height

    # Estimate times (rough estimates based on GPU performance)
    # These are calibrated for RTX 3090/4090 class GPUs

    estimates = {
        'input': {
            'width': width,
            'height': height,
            'frames': nb_frames,
            'fps': current_fps,
            'duration': duration,
            'pixels': input_pixels
        },
        'output': {
            'width': output_width,
            'height': output_height,
            'frames': output_frames,
            'fps': output_fps,
            'pixels': output_pixels
        }
    }

    total_time = 0

    # Interpolation time (RIFE)
    if mode in ('interp', 'interpolate', 'both'):
        # RIFE GPU processing: more realistic estimates
        # RTX 3090/4090: ~0.3-0.8 sec per intermediate frame depending on resolution
        # For interp_factor=2.5: need to generate 1.5x intermediate frames
        intermediate_frames = (interp_factor - 1) * nb_frames

        # Time per frame varies significantly with resolution:
        # Note: Using conservative estimates based on inference_img.py (slower method)
        # If rife_interpolate_direct.py works, actual time will be 3-5x faster
        # 640x480:   ~1.0 sec/frame (inference_img.py) or ~0.2 sec (direct, if padding works)
        # 1920x1080: ~2.0 sec/frame (inference_img.py) or ~0.5 sec (direct)
        # 2560x1440: ~3.5 sec/frame (inference_img.py) or ~0.8 sec (direct)
        # 3840x2160: ~5.0 sec/frame (inference_img.py) or ~1.2 sec (direct)
        resolution_factor = input_pixels / (1920 * 1080)
        time_per_frame = 1.0 + (resolution_factor * 1.5)  # Conservative estimate for inference_img.py

        interp_time = intermediate_frames * time_per_frame
        estimates['interpolation'] = {
            'frames_to_generate': int(intermediate_frames),
            'estimated_time': interp_time,
            'time_per_frame': time_per_frame
        }
        total_time += interp_time

    # Upscaling time (Real-ESRGAN)
    if mode in ('upscale', 'both'):
        # Process output frames (after interpolation if 'both')
        frames_to_upscale = output_frames if mode == 'both' else nb_frames

        # Real-ESRGAN GPU processing: very conservative estimates
        # Based on real-world performance (frame-by-frame processing):
        # RTX 3090/4090 for 2x upscale:
        # 640x480:   ~0.8-1.2 sec/frame
        # 1920x1080: ~1.5-2.5 sec/frame
        # 2560x1440: ~3.0-4.0 sec/frame
        # For 4x upscale: ~3-4x slower
        resolution_factor = input_pixels / (1920 * 1080)
        base_time = 1.0 + (resolution_factor * 1.2)  # Very conservative base time for 2x
        scale_multiplier = 1.0 if scale == 2 else 3.5  # 4x is ~3.5x slower
        time_per_frame = base_time * scale_multiplier

        upscale_time = frames_to_upscale * time_per_frame
        estimates['upscaling'] = {
            'frames_to_process': frames_to_upscale,
            'estimated_time': upscale_time,
            'time_per_frame': time_per_frame
        }
        total_time += upscale_time

    # Overhead (model loading, video encoding, I/O, etc.)
    overhead = 60  # ~1 minute for model loading + encoding
    total_time += overhead

    estimates['total'] = {
        'estimated_seconds': total_time,
        'estimated_minutes': total_time / 60,
        'overhead': overhead
    }

    return estimates


def format_eta(estimates: dict) -> str:
    """Format ETA estimates into human-readable string"""
    lines = []
    lines.append("📊 Estimated Processing Time:")

    inp = estimates['input']
    out = estimates['output']

    lines.append(f"   Input:  {inp['width']}x{inp['height']}, {inp['frames']} frames @ {inp['fps']:.1f}fps ({inp['duration']:.1f}s)")
    lines.append(f"   Output: {out['width']}x{out['height']}, {out['frames']} frames @ {out['fps']:.1f}fps")
    lines.append("")

    if 'interpolation' in estimates:
        interp = estimates['interpolation']
        lines.append(f"   • Interpolation: {interp['frames_to_generate']} frames → ~{interp['estimated_time']/60:.1f} min")

    if 'upscaling' in estimates:
        upscale = estimates['upscaling']
        lines.append(f"   • Upscaling: {upscale['frames_to_process']} frames → ~{upscale['estimated_time']/60:.1f} min")

    total = estimates['total']
    lines.append(f"   • Overhead: ~{total['overhead']} sec (model loading, encoding)")
    lines.append("")
    lines.append(f"   ⏱️  TOTAL ETA: ~{total['estimated_minutes']:.1f} minutes ({int(total['estimated_seconds'])} seconds)")
    lines.append("")
    lines.append(f"   💡 Note: Actual time varies based on GPU performance")

    return '\n'.join(lines)

def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    print(f"Loading config from: {config_path}")

    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    if not config:
        print(f"ERROR: Config file is empty: {config_path}")
        sys.exit(1)

    # Helper: normalize keys to detect similar names (handles accidental cyrillic 'с' in 'config_url')
    def _normalize_key(k: str) -> str:
        if not isinstance(k, str):
            return ''
        # Replace common Cyrillic 'с' (U+0441) with latin 'c' to tolerate typos like 'сofig_url'
        k2 = k.replace('\u0441', 'c')
        return k2.strip().lower()

    # Detect external config URL key (allow variations like config_url or сofig_url)
    remote_url = None
    for key, val in list(config.items()):
        if _normalize_key(key) == 'config_url' and isinstance(val, str) and val.strip():
            remote_url = val.strip()
            break

    # If external config URL present, try to download and parse it (JSON or YAML)
    if remote_url:
        print(f"Found external config URL: {remote_url}")

        def _fetch_remote(u: str) -> dict:
            import urllib.request
            import json
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "vastai_interup/1.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read()
                    # Try JSON first if content-type indicates JSON or URL endswith .json
                    ct = resp.headers.get('Content-Type', '') or ''
                    text = raw.decode('utf-8')
                    if ct.startswith('application/json') or u.lower().endswith('.json'):
                        try:
                            return json.loads(text)
                        except Exception:
                            pass
                    # Try JSON general parse
                    try:
                        return json.loads(text)
                    except Exception:
                        pass
                    # Fallback to YAML
                    try:
                        return yaml.safe_load(text)
                    except Exception as e:
                        raise RuntimeError(f"Failed to parse remote config as JSON or YAML: {e}")
            except Exception as e:
                raise RuntimeError(f"Failed to fetch remote config: {e}")

        try:
            remote_cfg = _fetch_remote(remote_url)
            if not isinstance(remote_cfg, dict):
                raise RuntimeError("Remote config is not a mapping/object")
            print("Remote config downloaded — validating...")

            # Validate video block in remote config
            video = remote_cfg.get('video')
            if not isinstance(video, dict):
                raise RuntimeError("Remote config must contain a 'video' mapping with processing parameters")

            # Expected video fields and types
            errors = []
            # input_dir optional, but if present must be string
            if 'input_dir' in video and not isinstance(video.get('input_dir'), str):
                errors.append("video.input_dir must be a string")
            # mode required-ish: check and coerce
            mode = video.get('mode')
            if mode is None:
                errors.append("video.mode is required in remote config")
            else:
                if not isinstance(mode, str) or mode not in ('upscale', 'interpolate', 'both', 'interp'):
                    errors.append("video.mode must be one of: upscale, interpolate, both, interp")
            # scale must be integer
            scale = video.get('scale')
            if scale is None:
                errors.append("video.scale is required in remote config")
            else:
                try:
                    if int(scale) < 1:
                        errors.append("video.scale must be a positive integer")
                except Exception:
                    errors.append("video.scale must be an integer")
            # target_fps must be integer
            tf = video.get('target_fps')
            if tf is None:
                errors.append("video.target_fps is required in remote config")
            else:
                try:
                    if int(tf) < 1:
                        errors.append("video.target_fps must be a positive integer")
                except Exception:
                    errors.append("video.target_fps must be an integer")

            if errors:
                raise RuntimeError("Remote config validation failed: " + "; ".join(errors))

            # Remote config valid — merge into local config (replace video block)
            config['video'] = video
            print("Remote config validated and applied (video block replaced)")

        except Exception as e:
            print(f"ERROR: Could not load/validate remote config from {remote_url}: {e}")
            sys.exit(1)

    return config


def download_input(input_name: str, config: dict = None) -> str:
    """Download input video from B2 using presigned URL from config, ENV or generate new one"""
    input_path = f"/workspace/input.mp4"

    # Check if input_name is a direct URL
    if input_name and input_name.startswith(('http://', 'https://')):
        print(f"[{ts()}] ✓ Input is a direct URL, downloading: {input_name}", flush=True)
        # Try wget first, then curl
        try:
            subprocess.run(['wget', '-O', input_path, input_name], check=True)
            print(f"[{ts()}] ✓ Downloaded via wget: {input_path}", flush=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            try:
                subprocess.run(['curl', '-L', '-o', input_path, input_name], check=True)
                print(f"[{ts()}] ✓ Downloaded via curl: {input_path}", flush=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"[{ts()}] ERROR: Failed to download from {input_name}", flush=True)
                sys.exit(1)

        # Verify downloaded file
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            print(f"ERROR: Downloaded file is empty or missing: {input_path}")
            sys.exit(1)

        # Check if it's a valid video
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', input_path], capture_output=True, text=True, check=True)
            if not result.stdout.strip():
                raise subprocess.CalledProcessError(1, 'ffprobe')
        except subprocess.CalledProcessError:
            print(f"ERROR: Downloaded file is not a valid video file: {input_path}")
            # Try to get more info
            try:
                result = subprocess.run(['file', input_path], capture_output=True, text=True)
                print(f"File type: {result.stdout}")
            except:
                pass
            try:
                result = subprocess.run(['head', '-c', '100', input_path], capture_output=True, text=True)
                print(f"First 100 bytes: {result.stdout}")
            except:
                pass
            sys.exit(1)

        print(f"[{ts()}] ✓ Downloaded file verified as valid video")
        return input_path

    # Priority 1: Check if input_url is in config.yaml (highest priority)
    input_url = None
    if config:
        video = config.get('video', {})
        input_url = video.get('input_url')
        if input_url:
            print(f"[{ts()}] ✓ Found input_url in config.yaml", flush=True)
            print(f"[{ts()}] Downloading input from: {input_url}", flush=True)
            # Try wget first, then curl
            try:
                subprocess.run(['wget', '-O', input_path, input_url], check=True)
                print(f"[{ts()}] ✓ Downloaded via wget: {input_path}", flush=True)
                return input_path
            except (subprocess.CalledProcessError, FileNotFoundError):
                try:
                    subprocess.run(['curl', '-L', '-o', input_path, input_url], check=True)
                    print(f"[{ts()}] ✓ Downloaded via curl: {input_path}", flush=True)
                    return input_path
                except (subprocess.CalledProcessError, FileNotFoundError):
                    print(f"[{ts()}] ERROR: Failed to download from {input_url}", flush=True)
                    sys.exit(1)

    # Priority 2: Check if INPUT_URL env var is set (from run_slim_vast.py)
    # But verify that it matches the input_name from config!
    input_url = os.environ.get('INPUT_URL')

    if input_url:
        # Check if URL contains the expected filename
        if input_name in input_url:
            print(f"✓ Found INPUT_URL in ENV (matches config input: {input_name})")
            print(f"Downloading input from: {input_url}")
            # Try wget first, then curl
            try:
                subprocess.run(['wget', '-O', input_path, input_url], check=True)
                print(f"✓ Downloaded via wget: {input_path}")
                return input_path
            except (subprocess.CalledProcessError, FileNotFoundError):
                try:
                    subprocess.run(['curl', '-L', '-o', input_path, input_url], check=True)
                    print(f"✓ Downloaded via curl: {input_path}")
                except (subprocess.CalledProcessError, FileNotFoundError):
                    print(f"ERROR: Failed to download from {input_url}")
                    sys.exit(1)
        else:
            print(f"⚠️  INPUT_URL in ENV doesn't match config input: {input_name}")
            print(f"   ENV URL: {input_url[:80]}...")
            print(f"   Expected: {input_name}")
            print(f"   Will try to generate new presigned URL for {input_name}")

    # Priority 3: Generate presigned URL using B2 credentials from ENV
    print(f"✗ No input_url in config or INPUT_URL in ENV")
    print(f"Trying to generate presigned URL for: {input_name}")

    b2_key = os.environ.get('B2_KEY')
    b2_secret = os.environ.get('B2_SECRET')
    b2_bucket = os.environ.get('B2_BUCKET', 'noxfvr-videos')
    b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')

    if not b2_key or not b2_secret:
        print(f"ERROR: No B2 credentials in ENV (B2_KEY, B2_SECRET)")
        print(f"Cannot generate presigned URL for {input_name}")
        print(f"")
        print(f"Solutions:")
        print(f"  1. Upload {input_name} to B2 first")
        print(f"  2. Set INPUT_URL env var with presigned URL")
        print(f"  3. Ensure B2_KEY and B2_SECRET are set in ENV")
        sys.exit(1)

    # Try to generate presigned URL
    try:
        print(f"Generating presigned URL for s3://{b2_bucket}/input/{input_name}...")

        # Use b2_presign module
        sys.path.insert(0, '/workspace/project')
        import b2_presign

        urls = b2_presign.generate_presigned(
            b2_bucket,
            f"input/{input_name}",
            b2_key,
            b2_secret,
            b2_endpoint,
            os.environ.get('B2_REGION'),
            expires=3600  # 1 hour
        )

        input_url = urls['get_url']
        print(f"✓ Generated presigned URL")

        # Download using generated URL
        print(f"Downloading from B2...")
        try:
            subprocess.run(['wget', '-O', input_path, input_url], check=True)
            print(f"✓ Downloaded via wget: {input_path}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            subprocess.run(['curl', '-L', '-o', input_path, input_url], check=True)
            print(f"✓ Downloaded via curl: {input_path}")

        # Verify downloaded file
        if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
            print(f"ERROR: Downloaded file is empty or missing: {input_path}")
            sys.exit(1)

        # Check if it's a valid video
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', input_path], capture_output=True, text=True, check=True)
            if not result.stdout.strip():
                raise subprocess.CalledProcessError(1, 'ffprobe')
        except subprocess.CalledProcessError:
            print(f"ERROR: Downloaded file is not a valid video file: {input_path}")
            # Try to get more info
            try:
                result = subprocess.run(['file', input_path], capture_output=True, text=True)
                print(f"File type: {result.stdout}")
            except:
                pass
            try:
                result = subprocess.run(['head', '-c', '100', input_path], capture_output=True, text=True)
                print(f"First 100 bytes: {result.stdout}")
            except:
                pass
            sys.exit(1)

        print(f"✓ Downloaded file verified as valid video")

        return input_path

    except Exception as e:
        print(f"ERROR: Failed to generate presigned URL or download: {e}")
        print(f"")
        print(f"Make sure {input_name} is uploaded to s3://{b2_bucket}/input/{input_name}")
        sys.exit(1)


def run_pipeline(input_path: str, output_dir: str, config: dict) -> str:
    """Run pipeline.py with parameters from config"""
    video = config.get('video', {})
    advanced = config.get('advanced', {})

    mode = video.get('mode', 'both')
    scale = video.get('scale', 2)
    target_fps = video.get('target_fps', 60)
    prefer = advanced.get('prefer', 'auto')

    # Calculate interp_factor from target_fps (assuming 24fps source)
    # pipeline.py will recalculate exact factor from actual fps
    interp_factor = target_fps / 24.0

    print("", flush=True)
    print(f"[{ts()}] === Running pipeline ===", flush=True)
    print(f"[{ts()}] Input:  {input_path}", flush=True)
    print(f"[{ts()}] Output: {output_dir}", flush=True)
    print(f"[{ts()}] Mode:   {mode}", flush=True)
    print(f"[{ts()}] Scale:  {scale}x", flush=True)
    print(f"[{ts()}] FPS:    {target_fps} (factor: {interp_factor:.2f})", flush=True)
    print(f"[{ts()}] Prefer: {prefer}", flush=True)
    print("", flush=True)

    # Calculate and display ETA
    try:
        estimates = estimate_processing_time(input_path, mode, scale, target_fps)
        print(format_eta(estimates), flush=True)
        print("", flush=True)
    except Exception as e:
        print(f"⚠️  Could not calculate ETA: {e}", flush=True)
        print("", flush=True)

    print("⏳ Processing started (no live progress bar from pipeline.py)...", flush=True)
    print("   - For 'both' mode: interpolation first, then upscale", flush=True)
    print("   - Check container logs for detailed progress", flush=True)
    print("", flush=True)

    # Build command
    cmd = [
        'python3', '/workspace/project/pipeline.py',
        '--input', input_path,
        '--output', output_dir,
        '--mode', mode,
        '--prefer', prefer
    ]

    if mode in ('upscale', 'both'):
        cmd.extend(['--scale', str(scale)])

    if mode in ('interp', 'interpolate', 'both'):
        cmd.extend(['--target-fps', str(target_fps)])

    print(f"Command: {' '.join(cmd)}", flush=True)
    print("", flush=True)

    # Print start time
    import datetime
    start_time = datetime.datetime.now()
    print(f"[{ts()}] 🚀 Starting pipeline.py...", flush=True)
    print("", flush=True)
    sys.stdout.flush()

    # Run pipeline with unbuffered output (PYTHONUNBUFFERED=1)
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'  # Force unbuffered output

    try:
        # Use Popen instead of run to stream output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            env=env
        )

        # Stream output line by line
        for line in process.stdout:
            print(line, end='', flush=True)

        # Wait for completion
        return_code = process.wait()

        if return_code != 0:
            print("", flush=True)
            print(f"[{ts()}] ERROR: Pipeline failed with exit code {return_code}", flush=True)
            sys.exit(1)

        # Print completion time and duration
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        print("", flush=True)
        print(f"[{ts()}] ✓ Pipeline completed successfully", flush=True)
        print(f"[{ts()}] ⏱️  Duration: {duration}", flush=True)
    except Exception as e:
        print(f"[{ts()}] ERROR: Pipeline execution failed: {e}", flush=True)
        sys.exit(1)

    # Find output file
    import glob
    # First try top-level .mp4 files
    output_files = glob.glob(f"{output_dir}/*.mp4")

    # If nothing found, try recursive search and other common video extensions
    if not output_files:
        print(f"WARNING: No top-level .mp4 found in {output_dir}. Attempting recursive search and alternate extensions...")
        # recursive search for .mp4 (case-insensitive)
        recursive_mp4 = glob.glob(f"{output_dir}/**/*.mp4", recursive=True)
        recursive_MP4 = glob.glob(f"{output_dir}/**/*.MP4", recursive=True)
        candidates = recursive_mp4 + recursive_MP4

        # Try common other extensions
        for ext in ['mkv','mov','avi','webm','mpeg','mpg']:
            candidates += glob.glob(f"{output_dir}/**/*.{ext}", recursive=True)
            candidates += glob.glob(f"{output_dir}/**/*.{ext.upper()}", recursive=True)

        # Deduplicate while preserving order
        seen = set()
        candidates_uniq = []
        for c in candidates:
            if c not in seen:
                seen.add(c)
                candidates_uniq.append(c)

        if candidates_uniq:
            # Prefer largest file (likely the rendered video)
            candidates_uniq.sort(key=lambda p: (os.path.getsize(p) if os.path.exists(p) else 0), reverse=True)
            output_file = candidates_uniq[0]
            print(f"Found candidate output file by recursive search: {output_file}")
            print("Listing top-level output directory (ls -la):")
            try:
                subprocess.run(['ls', '-la', output_dir], check=False)
            except Exception:
                pass
            print("Listing recursive tree (find):")
            try:
                subprocess.run(['find', output_dir, '-maxdepth', '3', '-type', 'f', '-ls'], check=False)
            except Exception:
                pass
            print(f"Using {output_file} as the output file for upload")
        else:
            # No candidates found - print diagnostics and fail
            print(f"ERROR: No output .mp4 found in {output_dir}")
            print("Diagnostic: top-level listing:")
            try:
                subprocess.run(['ls', '-la', output_dir], check=False)
            except Exception:
                pass
            print("Diagnostic: recursive listing (up to depth 3):")
            try:
                subprocess.run(['find', output_dir, '-maxdepth', '3', '-type', 'f', '-ls'], check=False)
            except Exception:
                pass
            sys.exit(2)
    else:
        output_file = output_files[0]
        print(f"✓ Found output: {output_file}")

    return output_file


def upload_output(output_file: str, config: dict, b2_output_key: str = None):
    """Upload output to B2 using container_upload.py"""
    video = config.get('video', {})
    output_name = video.get('output', 'output.mp4')

    # Get B2 settings from ENV (set by run_slim_vast.py) or config
    b2_bucket = os.environ.get('B2_BUCKET', config.get('b2', {}).get('bucket', 'noxfvr-videos'))
    b2_endpoint = os.environ.get('B2_ENDPOINT', config.get('b2', {}).get('endpoint', 'https://s3.us-west-004.backblazeb2.com'))

    # If caller provided explicit b2_output_key (preferred for batch), use it.
    if b2_output_key:
        # Explicit caller-provided key (highest priority, used by batch processing)
        computed_key = b2_output_key
    else:
        # If the container was launched with B2_OUTPUT_KEY in the environment (single-file runs),
        # respect that value. Otherwise fall back to config.video.output (or default 'output.mp4').
        env_key = os.environ.get('B2_OUTPUT_KEY')
        if env_key:
            computed_key = env_key
            print(f"Info: Using B2_OUTPUT_KEY from environment: {computed_key}")
        else:
            # Prefer the output name declared in the config (this is how batch processing sets per-file names).
            computed_key = f"output/{output_name}"
            env_key = os.environ.get('B2_OUTPUT_KEY')
            if env_key and env_key != computed_key:
                # Log that env key exists but we prefer per-file config key for batch
                print(f"Info: B2_OUTPUT_KEY env present ({env_key}) but using config-derived key: {computed_key}")

    b2_output_key = computed_key

    print("")
    print("=== Uploading output ===")
    print(f"File:   {output_file}")
    print(f"Bucket: {b2_bucket}")
    print(f"Key:    {b2_output_key}")
    print("")

    # Copy to final location
    final_output = "/workspace/final_output.mp4"
    subprocess.run(['cp', output_file, final_output], check=True)
    subprocess.run(['ls', '-lh', final_output], check=True)

    # Upload using container_upload.py
    try:
        subprocess.run([
            'python3', '/workspace/project/scripts/container_upload.py',
            final_output,
            b2_bucket,
            b2_output_key,
            b2_endpoint
        ], check=True)
        print("")
        print("✓ Upload completed successfully")
        # Echo exact S3 path for visibility in logs
        try:
            print(f"Uploaded to s3://{b2_bucket}/{b2_output_key}")
        except Exception:
            pass
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Upload failed with exit code {e.returncode}")
        sys.exit(1)


def process_batch_input_dir(input_dir: str, config: dict) -> bool:
    """Process all videos in B2 input_dir sequentially"""
    import b2_presign

    bucket = os.environ.get('B2_BUCKET', 'noxfvr-videos')
    b2_key = os.environ.get('B2_KEY')
    b2_secret = os.environ.get('B2_SECRET')

    if not b2_key or not b2_secret:
        print("ERROR: B2_KEY and B2_SECRET required for batch processing")
        sys.exit(1)

    # Get list of files
    prefix = input_dir if input_dir.startswith('input/') else f'input/{input_dir}'
    print(f"Getting file list from B2: {bucket}/{prefix}")
    try:
        # Pass explicit B2 credentials and endpoint to list_objects so b2_presign can authorize
        b2_endpoint = os.environ.get('B2_ENDPOINT') or config.get('b2', {}).get('endpoint')
        b2_region = os.environ.get('B2_REGION') or config.get('b2', {}).get('region')
        # Debug: print presence of credentials and endpoint (do not print secret values)
        print(f"Debug: env B2_KEY_set={'yes' if bool(b2_key) else 'no'} B2_SECRET_set={'yes' if bool(b2_secret) else 'no'} B2_ENDPOINT_set={'yes' if bool(b2_endpoint) else 'no'} B2_REGION={b2_region}")
        sys.stdout.flush()
        # Ensure fallback: if b2_key/b2_secret missing here, try config's b2
        if (not b2_key or not b2_secret) and isinstance(config, dict):
            b2_cfg = config.get('b2', {})
            if not b2_key:
                b2_key = b2_cfg.get('key') or b2_cfg.get('access_key') or b2_cfg.get('B2_KEY')
            if not b2_secret:
                b2_secret = b2_cfg.get('secret') or b2_cfg.get('secret_key') or b2_cfg.get('B2_SECRET')

        objects = b2_presign.list_objects(bucket, prefix, b2_key, b2_secret, b2_endpoint, b2_region)
        video_files = [obj for obj in objects if obj['key'].endswith('.mp4')]

        # Check existing outputs in bucket and skip already-processed files
        try:
            existing_outputs = b2_presign.list_objects(bucket, 'output/', b2_key, b2_secret, b2_endpoint, b2_region)
            existing_output_basenames = [os.path.basename(o.get('key', '')) for o in existing_outputs]
        except Exception as _e:
            print(f"Warning: could not list existing outputs for skip-check: {_e}")
            existing_output_basenames = []

        # Honor overwrite flag from config: if True, reprocess even when outputs already exist
        try:
            video_overwrite = bool(config.get('video', {}).get('overwrite', False))
        except Exception:
            video_overwrite = False

        filtered_files = []
        skipped_existing = 0
        for obj in video_files:
            original_key = obj.get('key', '')
            original_name = Path(original_key).stem
            # Also consider the suffix after the first underscore (if present)
            alt_name = None
            alt_name_with_underscore = None
            if '_' in original_name:
                alt_name = original_name.split('_', 1)[1]
                alt_name_with_underscore = '_' + alt_name

            # If any existing output basename equals or contains the original_name or alt_name variants, consider it processed
            matches = []
            for b in existing_output_basenames:
                if not b:
                    continue
                if original_name == Path(b).stem or original_name in b:
                    matches.append(b)
                    continue
                if alt_name and (alt_name == Path(b).stem or alt_name in b):
                    matches.append(b)
                    continue
                if alt_name_with_underscore and (alt_name_with_underscore == Path(b).stem or alt_name_with_underscore in b):
                    matches.append(b)
                    continue

            if matches and not video_overwrite:
                # Skip existing outputs (default behavior)
                print(f"⚠️  Skipping {original_key} — output already exists in bucket (matched by: {Path(matches[0]).stem})")
                # Log all matched output keys for diagnostics
                if matches:
                    print("    Matched outputs:")
                    for m in matches:
                        print(f"      - {m}")
                skipped_existing += 1
                continue

            if matches and video_overwrite:
                # Overwrite enabled — reprocess despite existing outputs
                print(f"ℹ️  Overwrite enabled — reprocessing {original_key} despite existing outputs")
                if matches:
                    print("    Matched outputs (will be overwritten):")
                    for m in matches:
                        print(f"      - {m}")

            filtered_files.append(obj)

        video_files = filtered_files
        if skipped_existing:
            print(f"Skipped {skipped_existing} files because outputs already present in bucket/output/")

        # === Deduplicate by canonical name before processing ===
        # Canonical name: part after first '_' including leading underscore if present, e.g.
        # '34_[VCB-Studio] ...' -> '_[VCB-Studio] ...'
        unique_map = {}  # canonical -> (obj, prefix_num or None)
        duplicates = []
        for obj in video_files:
            key = obj.get('key', '')
            stem = Path(key).stem
            # derive canonical: prefer alt_name_with_underscore when present
            if '_' in stem:
                suffix = stem.split('_', 1)[1]
                canonical = '_' + suffix
            else:
                canonical = stem

            # try to parse numeric prefix (if any) for deterministic selection
            prefix_num = None
            try:
                if '_' in stem:
                    prefix_part = stem.split('_', 1)[0]
                    if prefix_part.isdigit():
                        prefix_num = int(prefix_part)
            except Exception:
                prefix_num = None

            if canonical not in unique_map:
                unique_map[canonical] = (obj, prefix_num)
            else:
                existing_obj, existing_prefix = unique_map[canonical]
                # Prefer the one with a numeric prefix (lower number wins), else keep existing (first)
                replace = False
                if prefix_num is not None and existing_prefix is not None:
                    if prefix_num < existing_prefix:
                        replace = True
                elif prefix_num is not None and existing_prefix is None:
                    # prefer one that has numeric prefix
                    replace = True

                if replace:
                    duplicates.append(existing_obj)
                    unique_map[canonical] = (obj, prefix_num)
                else:
                    duplicates.append(obj)

        if duplicates:
            print(f"Deduplicated {len(duplicates)} files by canonical name; will process {len(unique_map)} unique items")
            for d in duplicates:
                print(f"⚠️  Duplicate skipped: {d.get('key')} (canonical duplicate)")

        # Final list to process: the unique objects (preserve deterministic order by sorting by canonical)
        # Convert map to list
        video_files = [v[0] for k, v in sorted(unique_map.items(), key=lambda x: x[0])]
    except Exception as e:
        print(f"ERROR listing B2 objects: {e}")
        sys.exit(1)

    if not video_files:
        print(f"No .mp4 files found in {bucket}/{prefix}")
        return False

    # Summary: clear, single-line overview for container logs/monitoring
    total = len(video_files)
    print("")
    print("=== Batch Summary ===", flush=True)
    print(f"  Source bucket: {bucket}", flush=True)
    print(f"  Source prefix: {prefix}", flush=True)
    print(f"  Files to process: {total}", flush=True)
    # Destination/ upload info (default to output/ key namespace)
    out_bucket = os.environ.get('B2_BUCKET', config.get('b2', {}).get('bucket', bucket)) if isinstance(config, dict) else bucket
    print(f"  Output will be uploaded to bucket: {out_bucket} under prefix: output/", flush=True)
    print("======================", flush=True)

    print(f"Found {total} video files to process", flush=True)

    output_dir = "/workspace/output"
    os.makedirs(output_dir, exist_ok=True)

    for i, obj in enumerate(video_files, 1):
        original_key = obj.get('key')
        # Compute expected output name and upload target
        original_name = Path(original_key).stem
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        expected_output_name = f"{original_name}_{timestamp}.mp4"
        upload_bucket = os.environ.get('B2_BUCKET', config.get('b2', {}).get('bucket', bucket)) if isinstance(config, dict) else bucket
        upload_key = f"output/{expected_output_name}"

        # Clear visible header for this file (explicit and flushed)
        print("\n" + "-"*60, flush=True)
        print(f"Processing file {i}/{total}", flush=True)
        print(f"  Source: {original_key}", flush=True)
        print(f"  Local output path: /workspace/output/{expected_output_name}", flush=True)
        print(f"  Will upload to: s3://{upload_bucket}/{upload_key}", flush=True)
        print("-"*60, flush=True)

        # Generate presigned URL
        try:
            urls = b2_presign.generate_presigned(bucket, obj['key'], b2_key, b2_secret, b2_endpoint, b2_region)
            input_url = urls['get_url']
        except Exception as e:
            print(f"ERROR generating presigned URL for {obj['key']}: {e}")
            continue

        # Create temp config for this file
        temp_config = dict(config)
        temp_config['video']['input'] = input_url
        temp_config['video']['output'] = expected_output_name

        try:
            # Fail-fast: check disk size of the running container against requested allocation in config
            try:
                import shutil
                total_bytes = shutil.disk_usage('/').total
                total_gb = total_bytes // (1024 ** 3)
            except Exception:
                total_gb = None

            requested_gb = None
            try:
                vast_cfg = config.get('vast', {}) if isinstance(config, dict) else {}
                if vast_cfg.get('allocated_storage'):
                    requested_gb = int(vast_cfg.get('allocated_storage'))
                elif vast_cfg.get('min_disk'):
                    requested_gb = int(vast_cfg.get('min_disk'))
            except Exception:
                requested_gb = None

            if requested_gb and total_gb is not None and total_gb < requested_gb:
                print(f"ERROR: Container disk size is too small: total={total_gb}GB < requested allocated_storage={requested_gb}GB")
                print("This instance likely provisioned only ~10GB disk. Please set 'allocated_storage' in config.yaml (vast block) to >= the desired GB or use a preset with larger disk.")
                # Exit so the instance is not used for processing and user can choose another host
               # sys.exit(1)
        except Exception as e:
            print(f"ERROR: Failed to check disk size or requested allocation: {e}")
            sys.exit(1)

        try:
            # Download and process (log stages more explicitly)
            log_stage("Downloading input", obj['key'])
            input_path = download_input(input_url, temp_config)

            log_stage("Starting pipeline", obj['key'])
            output_file = run_pipeline(input_path, output_dir, temp_config)

            log_stage("Uploading result", expected_output_name)
            upload_output(output_file, temp_config, upload_key)
            print(f"✅ Completed processing {original_name}")
        except Exception as e:
            print(f"❌ Failed to process {original_name}: {e}")
            continue

    # Completed loop
    return True


def main(argv=None):
    argv = argv or sys.argv[1:]
    config_path = argv[0] if len(argv) > 0 else '/workspace/project/config.yaml'

    # Load config
    config = load_config(config_path)

    # Generate or reuse a per-run job identifier and start timestamp; expose to child processes via ENV
    try:
        import uuid
        job_id = os.environ.get('JOB_ID') or str(uuid.uuid4())
    except Exception:
        job_id = os.environ.get('JOB_ID') or 'unknown'
    job_start = os.environ.get('JOB_START') or datetime.now().isoformat()
    # Write to env so subprocesses (pipeline.py) see them
    os.environ['JOB_ID'] = job_id
    os.environ['JOB_START'] = job_start
    # Print run header
    try:
        print(f"\n=== RUN START: job_id={job_id} start={job_start} ===\n")
    except Exception:
        pass

    # Prefer env-driven input for containers (set by run_with_config.py when creating instance)
    video = config.get('video', {})

    # Batch mode: prefer input_b2_dir (short name) but fall back to explicit input_dir if first is empty
    input_b2 = video.get('input_b2_dir')
    input_dir_full = video.get('input_dir')
    if input_b2 or input_dir_full:
        # Try input_b2 first if present
        if input_b2:
            print(f"Detected batch input_b2_dir: {input_b2} -> attempting to process")
            processed = process_batch_input_dir(input_b2, config)
            if processed:
                return
            else:
                print(f"No files in input_b2_dir={input_b2}.")
        # Try full input_dir next
        if input_dir_full:
            print(f"Attempting to process input_dir: {input_dir_full}")
            processed = process_batch_input_dir(input_dir_full, config)
            if processed:
                return
            else:
                print(f"No files in input_dir={input_dir_full}.")
        # If config requested batch processing but nothing found, exit instead of falling back to single-file mode.
        print("No batch files found in either input_b2_dir or input_dir. Exiting (no single-file fallback).")
        try:
            print(FINAL_PIPELINE_MARKER)
        except Exception:
            pass
        sys.exit(0)

    # Single file mode: prefer INPUT_URL env, then config.video.input or video.input_url
    input_url = os.environ.get('INPUT_URL') or os.environ.get('INPUT_GET_URL') or video.get('input') or video.get('input_url')
    if not input_url:
        print("No input URL provided to container (env INPUT_URL or config.video.input). Nothing to do.")
        return

    print(f"Single-file mode: downloading and processing: {input_url}")
    inp = download_input(input_url, config)
    outdir = '/workspace/output'
    os.makedirs(outdir, exist_ok=True)
    out = run_pipeline(inp, outdir, config)
    upload_output(out, config)


if __name__ == '__main__':
    main()
