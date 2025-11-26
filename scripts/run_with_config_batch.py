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
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime

# Add parent dir to path to import local modules
sys.path.insert(0, str(Path(__file__).parent.parent))

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

# video detection helper (optional, fallback provided)
try:
    from scripts.utils import is_video_key
except Exception:
    def is_video_key(key, probe=False):
        try:
            k = (key or '').lower()
            for ext in ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.mjpeg', '.mpeg', '.mpg'):
                if k.endswith(ext):
                    return True
        except Exception:
            pass
        return False


def load_config(config_path: str = 'config.yaml') -> dict:
    """Load configuration from YAML file"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def main():
    parser = argparse.ArgumentParser(
        description='Batch process videos from B2 directory on Vast.ai using config.yaml'
    )
    parser.add_argument('--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    parser.add_argument('preset', nargs='?',
                        help='Preset name to use (matches keys in config.yaml presets: e.g. low, balanced, high, or a custom name). If omitted, uses vast.preset or balanced')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration and search results without creating instance')

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config from {args.config}: {e}")
        sys.exit(1)

    video_config = config.get('video', {})
    input_dir = video_config.get('input_dir')

    if not input_dir:
        print("❌ input_dir not specified in config.video.input_dir")
        print("For batch processing, set video.input_dir to the B2 directory path (e.g. 'kk4')")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"🚀 Vast.ai Batch Video Processing")
    print(f"{'='*60}\n")

    print("📹 Batch Settings:")
    print(f"  Input Dir:  {input_dir}")
    print(f"  Mode:       {video_config.get('mode', 'both')}")
    print(f"  Scale:      {video_config.get('scale', 2)}x")
    print(f"  Target FPS: {video_config.get('target_fps', 60)}")

    # Get B2 credentials
    b2_key = os.environ.get('B2_KEY')
    b2_secret = os.environ.get('B2_SECRET')
    bucket = os.environ.get('B2_BUCKET', 'noxfvr-videos')

    if not b2_key or not b2_secret:
        print("❌ B2_KEY and B2_SECRET environment variables required")
        sys.exit(1)

    # Get list of files in input_dir (avoid double 'input/' prefix)
    prefix = input_dir if input_dir.startswith('input/') else f'input/{input_dir}'
    print(f"\n📂 Getting file list from B2: {bucket}/{prefix}")
    try:
        # Pass explicit B2 credentials and endpoint/region to b2_presign
        b2_endpoint = os.environ.get('B2_ENDPOINT')
        b2_region = os.environ.get('B2_REGION')
        # Debug: show presence of credentials (do not print values)
        print(f"Debug: env B2_KEY_set={'yes' if bool(os.environ.get('B2_KEY')) else 'no'} B2_SECRET_set={'yes' if bool(os.environ.get('B2_SECRET')) else 'no'} B2_ENDPOINT_set={'yes' if bool(b2_endpoint) else 'no'} B2_REGION={b2_region}")
        sys.stdout.flush()
        objects = b2_presign.list_objects(bucket, prefix, os.environ.get('B2_KEY'), os.environ.get('B2_SECRET'), b2_endpoint, b2_region)
        # keep only .mp4 files, skip zero-size artifacts and skip file equal to input_dir+'.mp4'
        # accept common video container extensions via helper
        raw_files = [obj for obj in objects if is_video_key(obj.get('key',''))]
        video_files = []
        input_dir_name = Path(input_dir).name
        for obj in raw_files:
            key = obj.get('key', '')
            size = int(obj.get('size') or 0)
            # Log zero-size objects (do NOT skip): some B2 listings return 0 even for valid files
            if size == 0:
                print(f"⚠️  Note: object reports size 0 (will still attempt to process): {key}")
            # skip top-level file named like the directory (e.g., input/kk3.mp4 when listing input/kk3)
            if key.rstrip('/') == f"{input_dir}.mp4" or key.rstrip('/') == f"input/{input_dir_name}.mp4":
                print(f"⚠️  Ignoring directory-index file: {key}")
                continue
            video_files.append(obj)
    except Exception as e:
        print(f"❌ Error listing B2 objects: {e}")
        sys.exit(1)

    # Check existing outputs once to avoid reprocessing same originals
    try:
        output_objects = b2_presign.list_objects(bucket, 'output/', os.environ.get('B2_KEY'), os.environ.get('B2_SECRET'), b2_endpoint, b2_region)
        existing_output_keys = [o.get('key', '') for o in output_objects]
    except Exception as e:
        print(f"Warning: could not list existing outputs: {e}")
        existing_output_keys = []

    # Filter out files that already have outputs (match by original name substring)
    filtered_video_files = []
    skipped = 0
    for obj in video_files:
        original_name = Path(obj['key']).stem
        found = any(original_name in k for k in existing_output_keys)
        if found:
            print(f"⚠️  Skipping {obj['key']} — output already exists in bucket (matched by name: {original_name})")
            skipped += 1
        else:
            filtered_video_files.append(obj)

    video_files = filtered_video_files
    if not video_files:
        print(f"✅ No files to process after skipping {skipped} already-completed files.")
        sys.exit(0)

    print(f"✅ Found {len(video_files)} video files:")
    for obj in video_files:
        print(f"  - {obj['key']} ({obj.get('size', 'unknown')} bytes)")

    if args.dry_run:
        print("\n🔍 Dry run - stopping here (no instances will be created)")
        return

    # Process each file
    for i, obj in enumerate(video_files, 1):
        print(f"\n{'-'*40}")
        print(f"🎬 Processing file {i}/{len(video_files)}: {obj['key']}")
        print(f"{'-'*40}")

        # Generate presigned URL
        try:
            urls = b2_presign.generate_presigned(bucket, obj['key'], b2_key, b2_secret, b2_endpoint, b2_region)
            input_url = urls['get_url']
        except Exception as e:
            print(f"❌ Error generating presigned URL for {obj['key']}: {e}")
            continue

        # Create output name: original_name_timestamp.mp4
        original_name = Path(obj['key']).stem
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # Keep .mp4 output for backward compatibility
        output_name = f"{original_name}_{timestamp}.mp4"

        # Create temporary config
        temp_config = dict(config)
        temp_config['video']['input'] = input_url
        temp_config['video']['output'] = output_name

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(temp_config, f)
            temp_config_path = f.name

        try:
            # Run run_with_config.py with the temp config
            cmd = [sys.executable, str(Path(__file__).parent / 'run_with_config.py'), '--config', temp_config_path]
            if args.preset:
                cmd.append(args.preset)

            print(f"🚀 Starting instance for {original_name}...")
            result = subprocess.run(cmd, check=True)
            print(f"✅ Completed processing {original_name}")

        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to process {original_name}: exit code {e.returncode}")
        finally:
            # Clean up temp config
            try:
                os.unlink(temp_config_path)
            except:
                pass

    print(f"\n{'='*60}")
    print(f"✅ Batch processing complete! Processed {len(video_files)} files.")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
