#!/usr/bin/env python3
"""
run_slim_vast.py

Автоматический запуск обработки видео на Vast.ai с использованием slim Docker образа.
Загружает входной файл на B2, создаёт инстанс на Vast.ai, запускает обработку и скачивает результат.

Usage:
  python scripts/run_slim_vast.py \
    --input test_60_short.mp4 \
    --output output_processed.mp4 \
    --mode both \
    --scale 2 \
    --target-fps 60 \
    --min-vram 8 \
    --max-price 0.15

Modes:
  - upscale: только апскейл
  - interpolate: только интерполяция
  - both: апскейл + интерполяция (по умолчанию)
"""

import os
import sys
import argparse
import subprocess
from pathlib import Path

# Add parent dir to path to import local modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env from repo root if present (keep behaviour consistent with other scripts)
ROOT = Path(__file__).resolve().parents[1]
_env_path = ROOT / '.env'
if _env_path.exists():
    try:
        import importlib
        _dotenv = importlib.import_module('dotenv')
        load_dotenv = getattr(_dotenv, 'load_dotenv')
        load_dotenv(dotenv_path=str(_env_path))
    except Exception:
        try:
            with open(_env_path, 'r', encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith('#') or _line.startswith('//'):
                        continue
                    if '=' not in _line:
                        continue
                    _k, _v = _line.split('=', 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
        except Exception:
            print('Warning: failed to parse .env file; continuing')


try:
    import vast_submit
    import upload_b2
    import b2_presign
except ImportError as e:
    print(f"Error importing required modules: {e}")
    # define placeholders so static analysis and later code referencing these names won't crash during linting
    vast_submit = None
    upload_b2 = None
    b2_presign = None
    print("Make sure you're running from the project root or scripts/ directory")
    sys.exit(1)


def upload_to_b2(local_file: str, bucket: str, key: str) -> dict:
    """Upload file to B2 and return presigned URLs"""
    print(f"\n=== Uploading {local_file} to B2 ===")
    
    access_key = os.environ.get('B2_KEY')
    secret_key = os.environ.get('B2_SECRET')
    endpoint = os.environ.get('B2_ENDPOINT')
    region = os.environ.get('B2_REGION')
    
    if not access_key or not secret_key:
        raise RuntimeError("B2_KEY and B2_SECRET must be set in environment or .env file")
    
    if not endpoint:
        endpoint = 'https://s3.us-west-004.backblazeb2.com'
        print(f"Using default B2 endpoint: {endpoint}")
    
    try:
        get_url = upload_b2.upload_file(
            local_file, bucket, key,
            access_key, secret_key, endpoint, region,
            expires=604800,  # 1 week
            overwrite=False
        )
        print(f"Upload complete. Presigned GET URL generated (expires in 1 week)")
        return {'get_url': get_url, 'bucket': bucket, 'key': key}
    except Exception as e:
        print(f"Failed to upload to B2: {e}")
        raise


def generate_output_presigned_url(bucket: str, key: str, expires: int = 604800):
    """Generate presigned PUT URL for output file. Returns (put_url, get_url) tuple"""
    print(f"\n=== Generating presigned PUT URL for output ===")
    
    access_key = os.environ.get('B2_KEY')
    secret_key = os.environ.get('B2_SECRET')
    endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')
    region = os.environ.get('B2_REGION')
    
    try:
        urls = b2_presign.generate_presigned(
            bucket, key,
            access_key, secret_key, endpoint, region,
            expires=expires
        )
        print(f"Presigned PUT URL generated for s3://{bucket}/{key}")
        return urls['put_url'], urls['get_url']
    except Exception as e:
        print(f"Failed to generate presigned URLs: {e}")
        raise


def build_container_command(input_url: str, mode: str, scale: int, target_fps: int,
                           b2_bucket: str, b2_key: str, b2_secret: str, b2_endpoint: str, output_key: str,
                           prefer: str = 'auto', strict: bool = False,
                           smoke_seconds: int = 0, smoke_timeout: int = 180,
                           rife_model_url: str | None = None):
    """Build the command to run inside the container - using boto3 for upload"""

    # Path inside container
    input_path = "/workspace/input.mp4"
    output_dir = "/workspace/output"
    final_output = "/workspace/final_output.mp4"

    # Download input
    download_cmd = f'wget -O {input_path} "{input_url}" || curl -L -o {input_path} "{input_url}"'

    # Process video using pipeline.py (it creates files in output_dir)
    # NOTE: pipeline.py uses --interp-factor (multiplier) not --target-fps (absolute)
    # We'll calculate interp-factor assuming original is 24fps (typical)
    # For 60fps target: 60/24 = 2.5x factor
    process_args = [
        f"--input {input_path}",
        f"--output {output_dir}",
        f"--mode {mode}",
    ]

    if mode in ('upscale', 'both'):
        process_args.append(f"--scale {scale}")

    if mode in ('interpolate', 'both') or mode == 'interp':
        # Convert target_fps to interp_factor assuming 24fps source
        # This is approximate - pipeline.py will calculate exact factor from actual fps
        interp_factor = target_fps / 24.0  # Assume 24fps source
        process_args.append(f"--interp-factor {interp_factor:.2f}")

    process_cmd = f"python3 /workspace/project/pipeline.py {' '.join(process_args)}"

    # Find the actual output file and copy to predictable location
    find_and_copy = f'find {output_dir} -name "*.mp4" -type f -exec cp {{}} {final_output} \\;'

    # Verify file exists
    verify_file = f'ls -lh {final_output} && echo "Found output file, uploading to B2..."'

    # Upload using container helper script (reads creds from env)
    upload_script = f"python3 /workspace/project/scripts/container_upload.py {final_output} {b2_bucket} {output_key} {b2_endpoint}"

    # Use remote_runner.sh for simpler, env-driven execution inside container
    # Pass parameters via env to keep args_str small and avoid quoting/length issues
    env_vars = []
    if input_url:
        env_vars.append(f'INPUT_URL="{input_url}"')
    # Pass preferred backend into container so pipeline can use PyTorch/ncnn explicitly
    env_vars.append(f'PREFER="{prefer}"')
    env_vars.append(f'MODE="{mode}"')
    env_vars.append(f'SCALE="{scale}"')
    # approximate interp factor
    interp_factor = target_fps / 24.0
    env_vars.append(f'INTERP_FACTOR="{interp_factor:.2f}"')
    env_vars.append(f'TARGET_FPS="{target_fps}"')
    env_vars.append(f'B2_BUCKET="{b2_bucket}"')
    env_vars.append(f'B2_OUTPUT_KEY="{output_key}"')
    env_vars.append(f'B2_ENDPOINT="{b2_endpoint}"')
    # Do NOT embed secrets into args_str. B2_KEY/B2_SECRET will be passed via instance env mapping
    # so they are available inside the container without exposing them in printed commands.
    # If you need to pass non-sensitive variables, add them here explicitly.
    # e.g., env_vars.append(f'B2_SOME_FLAG="{some_flag}"')
    # Pass strict mode setting (false by default to allow fallback to NCNN/CPU)
    env_vars.append(f'STRICT="{str(strict).lower()}"')
    # Smoke-test parameters (optional)
    if smoke_seconds and int(smoke_seconds) > 0:
        env_vars.append(f'SMOKE_SECONDS="{int(smoke_seconds)}"')
        env_vars.append(f'SMOKE_TIMEOUT="{int(smoke_timeout)}"')
    # RIFE model URL to allow runtime model download if image lacks preinstalled models
    if rife_model_url:
        env_vars.append(f'RIFE_MODEL_URL="{rife_model_url}"')

    # Auto-generate BATCH_ARGS for remote batch upscaling heuristics (passed as env to remote runner)
    # Use min_vram hint from vast search (best-effort; remote actual GPU may differ but autoscript will re-tune)
    try:
        min_vram_hint = int(float(os.environ.get('VAST_MIN_VRAM', '0')) or 0)
    except Exception:
        min_vram_hint = 0
    # Also allow using value from b2_config or caller via env
    if min_vram_hint == 0 and os.environ.get('BATCH_MIN_VRAM'):
        try:
            min_vram_hint = int(os.environ.get('BATCH_MIN_VRAM'))
        except Exception:
            min_vram_hint = 0

    # Simple heuristics (tuned): be slightly more aggressive for ~10GB+ cards
    # You can override this by setting BATCH_ARGS env var before running the script.
    if min_vram_hint >= 24:
        batch_args = '--batch-size 16 --use-local-temp --save-workers 8 --tile-size 512'
    elif min_vram_hint >= 16:
        batch_args = '--batch-size 12 --use-local-temp --save-workers 8 --tile-size 512'
    elif min_vram_hint >= 10:
        # For ~10-12 GB cards (e.g. RTX 3080/3090 Ti variants), try larger batches and 512 tiles
        batch_args = '--batch-size 8 --use-local-temp --save-workers 8 --tile-size 512'
    elif min_vram_hint >= 8:
        batch_args = '--batch-size 4 --use-local-temp --save-workers 4 --tile-size 400'
    else:
        batch_args = '--batch-size 2 --use-local-temp --save-workers 2 --tile-size 256'

    env_vars.append(f'BATCH_ARGS="{batch_args}"')

    runner_cmd = '/workspace/project/scripts/remote_runner.sh'
    # Build final command as: env VARS bash /workspace/project/scripts/remote_runner.sh
    # Use 'bash' explicitly to avoid permission issues

    # Prefix: download fresh scripts from Git (allows quick fixes without rebuilding image)
    # Remove existing dir first if it exists, then clone fresh
    # Ensure we're not inside /workspace/project when removing it (prevents Git fatal error on some containers)
    # Determine repository URL: prefer REPO_URL env var, then project root config.yaml, then fallback to known upstream
    repo_url = os.environ.get('REPO_URL')
    if not repo_url:
        try:
            cfg_path = Path(__file__).resolve().parents[1] / 'config.yaml'
            if cfg_path.exists():
                import yaml
                with open(cfg_path, 'r', encoding='utf-8') as cf:
                    cfg = yaml.safe_load(cf) or {}
                    repo_url = cfg.get('repo_url') or cfg.get('repository')
        except Exception:
            repo_url = None

    if not repo_url:
        # Use the canonical upstream GitLab repo used by this project as a fallback
        repo_url = 'https://gitlab.com/zerotouchprod/vastai_interup.git'

    git_clone = f'cd / && rm -rf /workspace/project && git clone --depth 1 {repo_url} /workspace/project'

    env_prefix = ' '.join(env_vars)
    run_cmd = f"{git_clone} && {env_prefix} bash {runner_cmd}"

    # Note: vast.ai will handle image pull automatically before starting container
    # If you need to force pull latest, use a unique tag (e.g., pytorch-fat-MMDD:latest) instead of 'latest'

    # Combine commands: remote_runner handles download and diagnostics; keep args_str small
    full_cmd = run_cmd

    # Wrap in bash
    return f'bash -c \'{full_cmd}\''


def _normalize_image(image: str) -> str:
    """Pass through image name without modification.

    Previously attempted to normalize paths, but this caused issues.
    Now just returns the image name as-is.
    """
    return image


def create_vast_instance(image: str, cmd: str, min_vram: int, max_price: float,
                         wait_finish: bool = True, reuse_host_id: int = None, input_get_url: str = None,
                         min_price: float = None, gpu_name: str = None, disk_gb: int = None) -> dict:
    """Create Vast.ai instance and optionally wait for completion by delegating to vast_submit CLI helper.

    This mirrors the previous behavior: build CLI-style args and call `vast_submit.main(args)` which
    performs search/accept with the API, handling endpoint variants and payload quirks.
    """
    # Normalize image to avoid common user mistakes
    normalized_image = _normalize_image(image)
    image = normalized_image

    # We'll search offers and pick one, then call vast_submit.create_instance with env
    try:
        offers = vast_submit.search_offers(min_vram=min_vram, max_price=max_price, limit=40)
    except Exception as e:
        raise RuntimeError(f"Error searching offers: {e}")

    if not offers:
        raise RuntimeError("No offers found matching constraints")

    # Filter by reuse_host_id if requested
    if reuse_host_id:
        offers = [o for o in offers if o.get('host_id') == int(reuse_host_id)]
        if not offers:
            raise RuntimeError(f"No offers available on host {reuse_host_id}")

    # Filter by min_price if specified (removes too cheap/slow GPUs)
    if min_price:
        offers = [o for o in offers if o.get('dph_total', 0) >= min_price]
        if not offers:
            raise RuntimeError(f"No offers found with price >= ${min_price}/hr")

    # Filter by GPU name if specified
    if gpu_name:
        gpu_name_lower = gpu_name.lower()
        offers = [o for o in offers if gpu_name_lower in o.get('gpu_name', '').lower()]
        if not offers:
            raise RuntimeError(f"No offers found with GPU matching '{gpu_name}'")

    chosen = vast_submit.pick_offer(offers)
    if not chosen:
        raise RuntimeError("Failed to pick an offer")

    offer_id = str(chosen.get('id') or chosen.get('offer_id') or chosen.get('offer'))
    # Cast to str to avoid static typing warnings from linters/type checkers
    try:
        offer_summary = vast_submit.human_offer_summary(chosen)
    except Exception:
        offer_summary = repr(chosen)
    print('Selected offer:', str(offer_summary))

    # Build env to pass to the instance (read local credentials)
    env = {}
    if os.environ.get('B2_KEY'):
        env['B2_KEY'] = str(os.environ.get('B2_KEY'))
    if os.environ.get('B2_SECRET'):
        env['B2_SECRET'] = str(os.environ.get('B2_SECRET'))
    env['B2_ENDPOINT'] = str(os.environ.get('B2_ENDPOINT', ''))
    env['B2_BUCKET'] = str(os.environ.get('B2_BUCKET', ''))
    if input_get_url:
        env['INPUT_URL'] = str(input_get_url)

    # Options for instance creation: runtype='oneshot' prevents auto-restart on failure
    # This ensures container runs once and stops (no infinite restart loops)
    # options = {
    #     'runtype': 'oneshot'  # Run once, do not restart on failure
    # }
    # Use a plain dict and set keys to avoid static analysis treating all values as same type
    options = {}
    options['runtype'] = 'oneshot'  # Run once, do not restart on failure
    # If specific disk requested, add to options (Vast API accepts 'disk' in payload)
    if disk_gb:
        try:
            options['disk'] = int(disk_gb)
        except Exception:
            options['disk'] = disk_gb

    try:
        inst = vast_submit.create_instance(offer_id=offer_id, image=image, cmd=cmd, env=env, start=True, options=options)
        # Try to extract instance id from the response (same heuristics used in vast_submit.main)
        inst_id = None
        if isinstance(inst, dict):
            for key in ("id", "instance_id", "_id", "uuid", "name", "contract", "contract_id", "new_contract", "new_contract_id"):
                if key in inst and inst.get(key):
                    inst_id = str(inst.get(key))
                    break
            if not inst_id:
                for k in ("result", "instance", "instances", "data"):
                    v = inst.get(k)
                    if isinstance(v, dict):
                        for key in ("id", "instance_id", "_id", "uuid", "name", "contract", "contract_id", "new_contract"):
                            if key in v and v.get(key):
                                inst_id = str(v.get(key))
                                break
                    if inst_id:
                        break

        print('Instance created:')
        print(inst)
        if not inst_id:
            print('Warning: could not determine instance id from API response. Proceeding without wait.')
            return {'success': True, 'instance': inst}

        print('Using instance id:', inst_id)

        # Optionally wait for instance to finish (terminated). Timeout can be configured via VAST_WAIT_SECS env var.
        if wait_finish:
            try:
                timeout = int(os.environ.get('VAST_WAIT_SECS', str(24 * 3600)))
                final = vast_submit.wait_for_status(inst_id, ['terminated'], timeout=timeout, poll=10)
                print('Instance finished:')
                print(final)
                return {'success': True, 'instance': inst, 'instance_id': inst_id, 'final': final}
            except Exception as e:
                print(f'Error waiting for instance to finish: {e}')
                # Still return success but indicate that wait failed/timed out
                return {'success': True, 'instance': inst, 'instance_id': inst_id, 'wait_error': str(e)}

        # If not waiting for finish, optionally wait until running to ensure container started
        try:
            runinfo = vast_submit.wait_for_status(inst_id, ['running', 'ready'], timeout=120, poll=3)
            print('Instance running info:\n', runinfo)
        except Exception:
            # ignore short wait failures
            pass

        return {'success': True, 'instance': inst, 'instance_id': inst_id}
    except Exception as e:
        print(f"Failed to create instance: {e}")
        raise


def download_from_b2(get_url: str, output_path: str):
    """Download processed video from B2 (cross-platform).

    Tries (in order):
      1) urllib (stdlib) streaming download
      2) requests (if installed)
      3) external wget or curl if present on PATH

    Raises RuntimeError if all methods fail.
    """
    print(f"\n=== Downloading output from B2 ===")
    print(f"Saving to: {output_path}")

    # Ensure output directory exists
    try:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
    except Exception as e:
        print(f"Failed to create output directory: {e}")
        raise

    e_urllib = None
    e_req = None

    # 1) Try using urllib (works without external deps)
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(get_url, headers={"User-Agent": "vastai_interup/1.0"})
        with urllib.request.urlopen(req) as resp, open(output_path, 'wb') as out_f:
            total = resp.getheader('Content-Length')
            if total is not None:
                try:
                    total = int(total)
                except Exception:
                    total = None
            downloaded = 0
            chunk_size = 8192
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
            if total:
                print(f"Downloaded {downloaded}/{total} bytes")
            else:
                print(f"Downloaded {downloaded} bytes")
        print(f"Download complete: {output_path}")
        return
    except Exception as exc:
        e_urllib = exc
        print(f"urllib download failed: {exc}")

    # 2) Try using requests if available
    try:
        import requests
        try:
            with requests.get(get_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(output_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            print(f"Download complete using requests: {output_path}")
            return
        except Exception as exc:
            e_req = exc
            print(f"requests download failed: {exc}")
    except Exception:
        # requests not installed or import failed
        pass

    # 3) Fallback to external commands if present (wget / curl)
    try:
        import shutil

        wget_path = shutil.which('wget')
        curl_path = shutil.which('curl')

        if wget_path:
            try:
                subprocess.run([wget_path, '-O', output_path, get_url], check=True)
                print(f"Download complete using wget: {output_path}")
                return
            except subprocess.CalledProcessError as e:
                print(f"wget failed: {e}")

        if curl_path:
            try:
                subprocess.run([curl_path, '-L', '-o', output_path, get_url], check=True)
                print(f"Download complete using curl: {output_path}")
                return
            except subprocess.CalledProcessError as e:
                print(f"curl failed: {e}")
    except Exception as exc:
        print(f"Fallback to external commands failed: {exc}")

    # If we reach here, all attempts failed
    err_msgs = []
    if e_urllib:
        err_msgs.append(f"urllib: {e_urllib}")
    if e_req:
        err_msgs.append(f"requests: {e_req}")
    raise RuntimeError("All download methods failed. " + "; ".join(err_msgs))


def wait_for_b2_object(bucket: str, key: str, access_key: str, secret_key: str, endpoint: str, timeout: int = 3600, poll: int = 10):
    """Poll for object presence on B2 by generating presigned GET URL and issuing HEAD requests.

    Returns a valid GET URL when the object becomes available, or raises TimeoutError.
    """
    try:
        import requests
    except Exception:
        raise RuntimeError("requests is required for waiting on remote B2 object; please install requests")

    start = __import__('time').time()
    last_exc = None
    while True:
        if __import__('time').time() - start > timeout:
            raise TimeoutError(f"Timed out waiting for s3://{bucket}/{key} after {timeout}s. Last error: {last_exc}")
        try:
            urls = b2_presign.generate_presigned(bucket, key, access_key, secret_key, endpoint, os.environ.get('B2_REGION'), expires=3600)
            get_url = urls.get('get_url')
            if not get_url:
                last_exc = 'presign did not return get_url'
                raise RuntimeError(last_exc)
            # HEAD request to check presence
            r = requests.head(get_url, allow_redirects=True, timeout=15)
            if r.status_code == 200:
                # Optionally check content-length
                cl = r.headers.get('Content-Length') or r.headers.get('content-length')
                if cl is None or int(cl) > 0:
                    return get_url
            else:
                last_exc = f"HEAD returned {r.status_code}"
        except Exception as e:
            last_exc = e
        __import__('time').sleep(poll)


def main():
    parser = argparse.ArgumentParser(description='Run video processing on Vast.ai with slim Docker image')
    
    # Input/output
    parser.add_argument('--input', required=True, help='Local input video file')
    parser.add_argument('--output', default='output_processed.mp4', help='Local output video file')
    
    # Processing options
    parser.add_argument('--mode', choices=['upscale', 'interpolate', 'both'], default='both',
                       help='Processing mode: upscale, interpolate, or both')
    parser.add_argument('--scale', type=int, default=2, choices=[2, 4],
                       help='Upscale factor (2x or 4x)')
    parser.add_argument('--target-fps', type=int, default=60,
                       help='Target FPS for interpolation')
    
    # B2 options
    parser.add_argument('--bucket', default=os.environ.get('B2_BUCKET', 'noxfvr-videos'),
                       help='B2 bucket name')
    parser.add_argument('--input-key', help='B2 key for input (default: input/<filename>)')
    parser.add_argument('--output-key', help='B2 key for output (default: output/<filename>)')
    
    # Vast.ai options
    parser.add_argument('--image', 
                       default='',
                       help='Docker image to use')
    parser.add_argument('--min-vram', type=int, default=8,
                       help='Minimum GPU VRAM in GB')
    parser.add_argument('--max-price', type=float, default=0.15,
                       help='Maximum price per hour in USD')
    parser.add_argument('--min-price', type=float, default=None,
                       help='Minimum price per hour in USD (filters out too cheap/slow GPUs)')
    parser.add_argument('--gpu-name', type=str, default=None,
                       help='Filter by GPU name (e.g., "RTX 3090", "RTX 4080")')
    parser.add_argument('--reuse-host', metavar='INSTANCE_ID',
                       help='Reuse host from previous instance (faster - cached Docker image)')

    # Workflow options
    parser.add_argument('--skip-upload', action='store_true',
                       help='Skip uploading input (assumes already uploaded)')
    parser.add_argument('--skip-download', action='store_true',
                       help='Skip downloading output (just print URL)')
    parser.add_argument('--no-wait', action='store_true',
                       help='Do not wait for instance to finish')
    
    # Preferred backend
    parser.add_argument('--prefer', choices=['auto','ncnn','pytorch','ffmpeg'], default='auto',
                       help='Preferred backend for processing: ncnn, pytorch, ffmpeg, or auto')

    args = parser.parse_args()
    
    # Validate input file exists
    if not args.skip_upload and not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return 1
    
    # Determine B2 keys
    input_basename = os.path.basename(args.input)
    output_basename = os.path.basename(args.output)
    
    input_key = args.input_key or f'input/{input_basename}'
    output_key = args.output_key or f'output/{output_basename}'
    
    print("=" * 60)
    print("Vast.ai Slim Docker Video Processing")
    print("=" * 60)
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    print(f"Mode:   {args.mode}")
    if args.mode in ('upscale', 'both'):
        print(f"Scale:  {args.scale}x")
    if args.mode in ('interpolate', 'both'):
        print(f"FPS:    {args.target_fps}")
    print(f"Bucket: {args.bucket}")
    print(f"Min VRAM: {args.min_vram} GB")
    print(f"Max Price: ${args.max_price}/hr")
    print("=" * 60)
    
    try:
        # Step 1: Upload input to B2 (unless skipped)
        if args.skip_upload:
            print("\n=== Skipping upload (--skip-upload) ===")
            # Still need to generate presigned URL
            urls = b2_presign.generate_presigned(
                args.bucket, input_key,
                os.environ.get('B2_KEY'), os.environ.get('B2_SECRET'),
                os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com'),
                os.environ.get('B2_REGION'),
                expires=7200
            )
            input_get_url = urls['get_url']
        else:
            upload_result = upload_to_b2(args.input, args.bucket, input_key)
            input_get_url = upload_result['get_url']
        
        # Step 2: Get B2 credentials (will pass to container for boto3 upload)
        b2_key = os.environ.get('B2_KEY')
        b2_secret = os.environ.get('B2_SECRET')
        b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')

        # Step 2.5: Get host_id if reusing
        reuse_host_id = None
        if args.reuse_host:
            print(f"\n=== Getting host_id from instance {args.reuse_host} ===")
            try:
                prev_info = vast_submit.get_instance(args.reuse_host)
                if prev_info:
                    reuse_host_id = prev_info.get('instances', {}).get('host_id')
                    if reuse_host_id:
                        print(f"✓ Found host_id: {reuse_host_id}")
                        print(f"  Host: {prev_info.get('instances', {}).get('public_ipaddr', 'Unknown')}")
                        print(f"  GPU: {prev_info.get('instances', {}).get('gpu_name', 'Unknown')}")
                        print(f"  → Will search for offers ONLY on this host (Docker image cached!)")
                    else:
                        print(f"⚠️  Could not get host_id from instance {args.reuse_host}")
                else:
                    print(f"⚠️  Instance {args.reuse_host} not found")
            except Exception as e:
                print(f"⚠️  Error getting host info: {e}")
                print("Continuing without host reuse...")

        # Step 3: Build container command (passes credentials for boto3 upload)
        container_cmd = build_container_command(
            input_get_url, args.mode, args.scale, args.target_fps,
            args.bucket, b2_key, b2_secret, b2_endpoint, output_key,
            prefer=args.prefer,
            strict=False  # Allow fallback to NCNN/CPU if GPU fails
        )
        
        print(f"\n=== Container command ===")
        print(container_cmd)
        
        # Step 4: Create and run Vast.ai instance
        instance_result = create_vast_instance(
            args.image, container_cmd,
            args.min_vram, args.max_price,
            wait_finish=(not args.no_wait),
            reuse_host_id=reuse_host_id,
            input_get_url=input_get_url,
            min_price=args.min_price,
            gpu_name=args.gpu_name
        )
        
        if not instance_result['success']:
            print("\nError: Instance creation/execution failed")
            return 1
        
        # Step 5: File uploaded to B2, download URL shown in logs
        if args.skip_download:
            print("\n=== Skipping download (--skip-download) ===")
            print(f"Download URL will be shown in instance logs")
            print(f"Check logs: python scripts/show_logs.py <instance_id>")
        else:
            print("\n=== Downloading output from B2 ===")
            print("Generating download URL...")

            # Generate GET URL for downloading
            urls = b2_presign.generate_presigned(
                args.bucket, output_key,
                b2_key, b2_secret, b2_endpoint,
                os.environ.get('B2_REGION'),
                expires=604800  # 1 week
            )
            output_get_url = urls['get_url']

            # If instance_id is not available and --no-wait is not set, wait for the object to appear on B2
            if 'instance_id' not in instance_result and not args.no_wait:
                print(f"Waiting for output file to appear on B2...")
                try:
                    output_get_url = wait_for_b2_object(args.bucket, output_key, b2_key, b2_secret, b2_endpoint, timeout=3600, poll=10)
                    print(f"Output file is now available: {output_get_url}")
                except Exception as e:
                    print(f"Error waiting for output file: {e}")
                    return 1

            download_from_b2(output_get_url, args.output)
        
        print("\n" + "=" * 60)
        print("SUCCESS! Processing complete.")
        print("=" * 60)
        print(f"Output file: {args.output}")
        print(f"B2 location: s3://{args.bucket}/{output_key}")
        print(f"Download URL shown in instance logs")

        return 0
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
