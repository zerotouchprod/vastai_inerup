#!/usr/bin/env python3
"""
run_with_config_batch.py

Batch processing of videos from B2 directory on Vast.ai using config.yaml

Usage:
  python scripts/run_with_config_batch.py [--config config.yaml] [--preset balanced]
"""

import os
import sys
import argparse
import yaml
import subprocess
from pathlib import Path
# Ensure project root is on sys.path so local imports (vast_submit, b2_presign) work when running scripts directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env from project root if present. Prefer python-dotenv, else fallback to a simple parser.
_env_path = Path(__file__).resolve().parent.parent / '.env'
# Track whether .env provided missing credentials
ENV_FILE_LOADED = False
# Record whether env already had B2 creds before attempting to load .env
_initial_b2_env = bool(os.environ.get('B2_KEY') and os.environ.get('B2_SECRET'))
if _env_path.exists():
    try:
        import importlib
        _dotenv = importlib.import_module('dotenv')
        load_dotenv = getattr(_dotenv, 'load_dotenv')
        load_dotenv(dotenv_path=str(_env_path))
        ENV_FILE_LOADED = True
        print(f"Info: loaded environment variables from {_env_path}")
    except Exception:
        # fallback parser: don't overwrite existing env vars
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
                    _v = _v.strip().strip('"').strip('\'')
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
            ENV_FILE_LOADED = True
            print(f"Info: loaded environment variables from {_env_path} (fallback parser)")
        except Exception as _e:
            print(f"Warning: failed to parse .env: {_e}")


try:
    import vast_submit
    import upload_b2
    import b2_presign
except ImportError as e:
    vast_submit = None
    upload_b2 = None
    b2_presign = None
    print(f"Error importing required modules: {e}")
    print("Make sure you're running from the project root or scripts/ directory")
    sys.exit(1)


def load_config(config_path: str = 'config.yaml') -> dict:
    """Load configuration from YAML file"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def main():
    parser = argparse.ArgumentParser(
        description='Batch process videos from B2 directory on Vast.ai using config.yaml (single instance)'
    )
    parser.add_argument('--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    parser.add_argument('--bucket', help='B2 bucket name (overrides B2_BUCKET env)')
    parser.add_argument('--input-dir', help='Input directory in B2 (overrides config.video.input_dir)')
    parser.add_argument('preset', nargs='?',
                        help='Preset name to use (matches keys in config.yaml presets: e.g. low, balanced, high, or a custom name). If omitted, uses vast.preset or balanced')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration and search results without creating instance')
    parser.add_argument('--reuse-instance', help='Reuse host from this instance ID (finds host_id automatically)')

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config from {args.config}: {e}")
        sys.exit(1)

    # If config contains a remote config URL (key 'config_url' or common typo with Cyrillic 'с'),
    # fetch remote config, display it, and use it instead of local config.
    def _normalize_key(k: str) -> str:
        try:
            if not isinstance(k, str):
                return ''
            # Replace Cyrillic small 'с' (U+0441) with latin 'c'
            return k.replace('\u0441', 'c').strip().lower()
        except Exception:
            return ''

    remote_cfg = None
    remote_url = None
    for key, val in list(config.items()):
        if _normalize_key(key) == 'config_url' and isinstance(val, str) and val.strip():
            remote_url = val.strip()
            break

    if remote_url:
        print(f"Info: remote config URL found in local config: {remote_url}")
        # Fetch remote config (JSON preferred, then YAML)
        import urllib.request, json
        try:
            req = urllib.request.Request(remote_url, headers={"User-Agent": "vastai_interup/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                text = raw.decode('utf-8')
                ct = (resp.headers.get('Content-Type') or '').lower()
                parsed = None
                if ct.startswith('application/json') or remote_url.lower().endswith('.json'):
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = None
                if parsed is None:
                    # try JSON anyway
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = None
                if parsed is None:
                    try:
                        parsed = yaml.safe_load(text)
                    except Exception as e:
                        raise RuntimeError(f"Failed to parse remote config as JSON or YAML: {e}")

            if not isinstance(parsed, dict):
                raise RuntimeError("Remote config is not a mapping/object")

            # Print remote config preview
            print("\n=== Remote config preview (from config_url) ===")
            try:
                pretty = yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)
                print(pretty)
            except Exception:
                print(parsed)
            print("=== End remote config preview ===\n")

            # Validate presence of 'video' block in remote config
            if 'video' not in parsed or not isinstance(parsed.get('video'), dict):
                raise RuntimeError("Remote config must include a 'video' mapping block")

            # Replace local config with parsed remote config
            config = parsed
            print("Info: Replaced local config with remote config from config_url")

        except Exception as e:
            print(f"ERROR: Could not fetch or parse remote config from {remote_url}: {e}")
            sys.exit(1)

    video_config = config.get('video', {})
    input_dir = video_config.get('input_dir')
    # Do not override input_dir from CLI; batch script should read input_dir from config.yaml
    # Keep running even if input_dir is missing (container/run_with_config.py will read config)

    # Immediate B2 credential check (fail-fast): ensure we have credentials before doing any work
    b2_key = os.environ.get('B2_KEY')
    b2_secret = os.environ.get('B2_SECRET')
    bucket = args.bucket or os.environ.get('B2_BUCKET', 'noxfvr-videos')

    b2_from_config = False
    if (not b2_key or not b2_secret) and config is not None:
        b2_cfg = config.get('b2', {}) if isinstance(config, dict) else {}
        if not b2_key:
            val = b2_cfg.get('key') or b2_cfg.get('access_key') or b2_cfg.get('B2_KEY')
            if val:
                b2_key = val
                b2_from_config = True
        if not b2_secret:
            val = b2_cfg.get('secret') or b2_cfg.get('secret_key') or b2_cfg.get('B2_SECRET')
            if val:
                b2_secret = val
                b2_from_config = True
        if not args.bucket:
            bucket = b2_cfg.get('bucket') or bucket

    # Determine source of B2 credentials for logging (do NOT print secrets)
    if _initial_b2_env:
        b2_source = 'env'
    elif ENV_FILE_LOADED and not _initial_b2_env and os.environ.get('B2_KEY') and os.environ.get('B2_SECRET'):
        b2_source = '.env'
    elif b2_from_config:
        b2_source = 'config.yaml'
    else:
        b2_source = 'missing'
    print(f"Info: B2 credentials source: {b2_source} (bucket: {bucket})")

    if not b2_key or not b2_secret:
        print("❌ B2_KEY and B2_SECRET are required (set them in environment or in config.yaml under b2: key/secret)")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"🚀 Vast.ai Batch Sync Processing (Single Instance)")
    print(f"{'='*60}\n")

    print("📹 Batch Settings:")
    print(f"  Input Dir:  {input_dir or 'N/A'}")
    print(f"  Mode:       {video_config.get('mode', 'both')}")
    print(f"  Scale:      {video_config.get('scale', 2)}x")
    print(f"  Target FPS: {video_config.get('target_fps', 60)}")

    # Get list of files in input_dir. If not set, list the whole 'input/' prefix.
    if input_dir:
        prefix = input_dir if input_dir.startswith('input/') else f'input/{input_dir}'
    else:
        prefix = 'input/'
        print("⚠️  Warning: video.input_dir not set in config.yaml — listing entire 'input/' prefix")
    print(f"\n📂 Getting file list from B2: {bucket}/{prefix}")
    try:
        objects = b2_presign.list_objects(bucket, prefix, b2_key, b2_secret)
        # Keep .mp4 files; don't skip zero-size (some listings report 0) but note them
        raw_files = [obj for obj in objects if obj.get('key','').endswith('.mp4')]
        video_files = []
        input_dir_name = Path(input_dir).name if input_dir else None
        for obj in raw_files:
            key = obj.get('key', '')
            size = int(obj.get('size') or 0)
            if size == 0:
                print(f"⚠️  Note: object reports size 0 (will still attempt to process): {key}")
            # skip index file named like the directory (e.g., input/kk3.mp4) only if we have input_dir
            if input_dir and (key.rstrip('/') == f"{input_dir}.mp4" or key.rstrip('/') == f"input/{input_dir_name}.mp4"):
                print(f"⚠️  Ignoring directory-index file: {key}")
                continue
            video_files.append(obj)
    except Exception:
        import traceback
        print("❌ Error listing B2 objects:")
        traceback.print_exc()
        print(f"Bucket={bucket} prefix={prefix} B2_KEY_set={'yes' if bool(b2_key) else 'no'} B2_SECRET_set={'yes' if bool(b2_secret) else 'no'}")
        sys.exit(1)

    if not video_files:
        print(f"❌ No .mp4 files found in {bucket}/{prefix}")
        sys.exit(1)

    print(f"✅ Found {len(video_files)} video files:")
    for obj in video_files:
        print(f"  - {obj['key']} ({obj.get('size', 'unknown')} bytes)")

    # Check for existing outputs in bucket and skip already-processed files
    try:
        output_objects = b2_presign.list_objects(bucket, 'output/', b2_key, b2_secret)
        existing_output_keys = [o.get('key', '') for o in output_objects]
    except Exception as _e:
        print(f"Warning: could not list existing outputs: {_e}")
        existing_output_keys = []

    # Respect video.overwrite: if true, reprocess even when output exists.
    filtered = []
    skipped = 0
    video_overwrite = False
    try:
        video_overwrite = bool(video_config.get('overwrite', False))
    except Exception:
        video_overwrite = False

    for obj in video_files:
        stem = Path(obj['key']).stem
        # Strict matching: compare basename stems (avoid substring false-positives)
        matches = [k for k in existing_output_keys if Path(k).stem == stem]
        already_exists = len(matches) > 0
        if already_exists and not video_overwrite:
            print(f"⚠️  Skipping {obj['key']} — output already exists (matched by name: {stem})")
            # Log exact matched output keys for diagnostics
            if matches:
                print("    Matched outputs:")
                for m in matches:
                    print(f"      - {m}")
            skipped += 1
        else:
            if already_exists and video_overwrite:
                print(f"ℹ️  Overwrite enabled — reprocessing {obj['key']} despite existing output (matched by name: {stem})")
                if matches:
                    print("    Matched outputs (will be overwritten):")
                    for m in matches:
                        print(f"      - {m}")
            filtered.append(obj)

    video_files = filtered
    if not video_files:
        print(f"✅ No files to process after skipping {skipped} already-completed files.")
        sys.exit(0)

    if args.dry_run:
        print("\n🔍 Dry run - stopping here (no instance will be created)")
        return

    # Instead of processing locally, launch single instance with input_dir
    # Before launching, show which config we will use (remote/local) and a redacted preview.
    try:
        cfg_source = remote_url if 'remote_url' in locals() and remote_url else args.config
    except Exception:
        cfg_source = args.config

    print(f"\nUsing config source: {cfg_source}")
    try:
        # Redact sensitive entries before printing
        cfg_to_print = dict(config) if isinstance(config, dict) else {}
        try:
            if isinstance(cfg_to_print.get('b2'), dict):
                b2copy = dict(cfg_to_print.get('b2'))
                if 'key' in b2copy:
                    b2copy['key'] = '<redacted>'
                if 'secret' in b2copy:
                    b2copy['secret'] = '<redacted>'
                cfg_to_print['b2'] = b2copy
        except Exception:
            pass
        print("--- Config preview used for launch ---")
        try:
            print(yaml.safe_dump(cfg_to_print, sort_keys=False, allow_unicode=True))
        except Exception:
            print(cfg_to_print)
        print("--- End config preview ---\n")
    except Exception as _e:
        print(f"Warning: failed to print config preview: {_e}")

    print(f"\n🚀 Launching single instance to process {len(video_files)} files sequentially...")

    # Temporarily modify config to remove input_dir and set input to something else
    # Actually, just run with the config as is, and let container handle input_dir

    # Process files sequentially: invoke run_with_config.py for each input file with --input-url and --output
    b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')
    runner = str(Path(__file__).parent / 'run_with_config.py')
    last_instance_id = None
    for idx, obj in enumerate(video_files, start=1):
        key = obj.get('key')
        # build http GET URL for B2 object
        input_url = f"{b2_endpoint.rstrip('/')}/{bucket}/{key.lstrip('/') }"
        # derive output name from object name (append timestamp to avoid collisions)
        base_name = Path(key).name
        stem = Path(base_name).stem
        ts = ''
        try:
            from datetime import datetime
            ts = '_' + datetime.now().strftime('%Y%m%d_%H%M%S')
        except Exception:
            ts = ''
        output_name = f"{stem}{ts}.mp4"

        cmd = [sys.executable, runner, '--config', args.config, '--input-url', input_url, '--output', output_name]
        if args.bucket:
            cmd.extend(['--bucket', args.bucket])
        if args.reuse_instance:
            cmd.extend(['--reuse-instance', args.reuse_instance])
        if args.preset:
            cmd.append(args.preset)

        # Ensure container/upload uses the intended output key (original name + timestamp)
        # Set B2_OUTPUT_KEY env so entrypoint/container will upload to s3://{bucket}/output/{output_name}
        env_override = os.environ.copy()
        env_override['B2_OUTPUT_KEY'] = f"output/{output_name}"

        print(f"\n--- Processing file {idx}/{len(video_files)}: {key}")
        print(f"    Input URL: {input_url}")
        print(f"    Output name: {output_name}")
        print(f"    Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env_override)
            print(f"✅ Completed processing {key}")
            if result.stdout:
                print("--- Child stdout ---")
                print(result.stdout)
            if result.stderr:
                print("--- Child stderr (non-fatal) ---")
                print(result.stderr)

            # Try to read the instance id saved by run_with_config.py (if any)
            try:
                reuse_file = Path(__file__).parent.parent / '.last_instance'
                if reuse_file.exists():
                    with open(reuse_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip().splitlines()
                        if content:
                            last_line = content[-1].strip()
                            if last_line:
                                last_instance_id = last_line
                                print(f"Info: detected instance id from .last_instance: {last_instance_id}")
            except Exception as _e:
                print(f"Warning: failed to read .last_instance: {_e}")

        except subprocess.CalledProcessError as e:
            print(f"❌ Processing failed for {key}")
            print(f"  Command: {' '.join(cmd)}")
            print(f"  Return code: {e.returncode}")
            if hasattr(e, 'stdout') and e.stdout:
                print("--- Child stdout ---")
                print(e.stdout)
            if hasattr(e, 'stderr') and e.stderr:
                print("--- Child stderr ---")
                print(e.stderr)
            import traceback
            traceback.print_exc()
            # continue to next file rather than aborting whole batch
            print("Continuing with next file...")
            continue

    # After processing all files, if we detected an instance id from any successful run,
    # automatically launch monitor_instance.py to follow that instance.
    try:
        if last_instance_id:
            monitor_path = Path(__file__).parent.parent / 'monitor_instance.py'
            if monitor_path.exists():
                print(f"\n🚨 Starting monitor for instance: {last_instance_id}")
                monitor_cmd = [sys.executable, str(monitor_path), last_instance_id]
                # Run monitor in the same terminal so user can interact (Ctrl+C to exit)
                try:
                    subprocess.run(monitor_cmd, check=False)
                except KeyboardInterrupt:
                    # Allow the user to interrupt monitoring
                    print("\nMonitor interrupted by user")
            else:
                print(f"Warning: monitor script not found at: {monitor_path}")
    except Exception as _e:
        print(f"Warning: failed to launch monitor: {_e}")


if __name__ == '__main__':
    main()
