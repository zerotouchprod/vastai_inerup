#!/usr/bin/env python3
"""
run_with_config.py

Запуск обработки видео на Vast.ai с использованием конфигурации из config.yaml
Поддерживает три пресета: low, balanced, high

Usage:
  python scripts/run_with_config.py [--config config.yaml] [--preset balanced]
"""

import os
import sys
import argparse
import yaml
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


def load_config(config_path: str = 'config.yaml') -> dict:
    """Load configuration from YAML file"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    return config


def extract_vast_params(vast_config: dict) -> dict:
    """Extract vast.ai search parameters from config"""
    params = {
        'min_vram': vast_config.get('min_vram', 8),
        'max_price': vast_config.get('max_price', 0.50),
        'limit': vast_config.get('limit', 40),
    }

    # Optional advanced filters
    optional_params = [
        'min_price', 'min_reliability', 'gpu_models', 'min_cuda',
        'min_dlperf', 'min_dlperf_per_dphtotal',
        'min_inet_down', 'min_inet_up',
        'min_cpu_cores', 'min_cpu_ram',
        'min_disk_bw', 'min_gpu_mem_bw',
        'datacenter', 'verified',
        'compute_cap', 'min_pcie_gen', 'static_ip',
        'geolocation_exclude', 'num_gpus',
        'min_disk', 'allocated_storage'
    ]

    for param in optional_params:
        if param in vast_config:
            params[param] = vast_config[param]

    # Handle offer type
    if 'type' in vast_config:
        params['offer_type'] = vast_config['type']

    return params


def select_vast_config(config: dict, cli_preset: str | None) -> dict:
    """Выбрать и слить пресет из config['presets'] и явный блок config['vast'].

    Преимущество: поля в config['vast'] переопределяют значения пресета.
    Приоритет источников для имени пресета: cli_preset -> config['vast'].get('preset') -> 'balanced'
    """
    presets = config.get('presets', {}) or {}
    explicit_vast = config.get('vast', {}) or {}

    # Determine preset name
    preset_name = None
    if cli_preset:
        preset_name = cli_preset
    elif isinstance(explicit_vast.get('preset'), str):
        preset_name = explicit_vast.get('preset')
    else:
        preset_name = 'balanced'

    # Start with preset defaults (if available)
    preset_cfg = {}
    if preset_name and preset_name in presets:
        preset_cfg = dict(presets[preset_name])  # shallow copy

    # Overlay explicit vast block: explicit values override preset
    merged = dict(preset_cfg)
    merged.update(explicit_vast)

    # Always set preset name on merged result for clarity
    merged['preset'] = preset_name
    return merged


def prioritize_offers_by_whitelist(offers: list, whitelist: list) -> list:
    """Локальная сортировка: поместить офферы с GPU в whitelist в начало списка."""
    if not whitelist:
        return offers
    wl = set([g.upper() for g in whitelist])
    def score(o):
        name = str(o.get('gpu_name', '')).upper()
        return 0 if any(w in name for w in wl) else 1
    return sorted(offers, key=score)


def try_search_with_fallback(vast_config: dict, max_attempts: int | None = None) -> tuple:
    """Попытаться найти офферы, при необходимости итеративно ослабляя фильтры.

    Возвращает (offers, used_config, attempt_log)
    """
    cfg = dict(vast_config)  # shallow copy
    attempt = 0
    attempt_log = []

    # Create a sequence of modifier functions that progressively relax constraints
    def mod_increase_price(c):
        if c.get('max_price'):
            c['max_price'] = round(float(c['max_price']) * 1.5, 3)
        else:
            c['max_price'] = 0.5
        return c

    def mod_decrease_vram(c):
        if c.get('min_vram'):
            c['min_vram'] = max(4, int(c['min_vram']) - 4)
        else:
            c['min_vram'] = 8
        return c

    def mod_lower_reliability(c):
        if c.get('min_reliability') is not None:
            try:
                val = float(c.get('min_reliability'))
                c['min_reliability'] = max(0.0, round(val - 0.1, 2))
            except Exception:
                c['min_reliability'] = 0.7
        else:
            c['min_reliability'] = 0.7
        return c

    def mod_remove_gpu_models(c):
        if 'gpu_models' in c:
            c.pop('gpu_models', None)
        return c

    def mod_disable_verified(c):
        c['verified'] = False
        return c

    def mod_broad(c):
        # Very broad final attempt
        c['min_vram'] = 6
        c['max_price'] = max(c.get('max_price', 0.5), 1.5)
        c['min_reliability'] = 0.6
        c.pop('gpu_models', None)
        c['verified'] = False
        return c

    modifiers = [
        lambda c: c,                 # original
        mod_increase_price,          # increase price
        mod_decrease_vram,           # decrease vram
        mod_lower_reliability,       # lower reliability
        mod_remove_gpu_models,       # remove gpu_models
        mod_disable_verified,        # allow unverified
        mod_broad                    # final broad sweep
    ]

    # Determine number of attempts: by default use all modifiers
    if max_attempts is None:
        max_attempts = len(modifiers)
    else:
        max_attempts = min(max_attempts, len(modifiers))

    for i in range(max_attempts):
        attempt += 1
        # Apply modifier i
        trial_cfg = dict(cfg)
        trial_cfg = modifiers[i](trial_cfg)

        # Build params and perform search
        params = extract_vast_params(trial_cfg)
        attempt_log.append({'attempt': attempt, 'params': params})
        try:
            offers = vast_submit.search_offers(**params)
        except Exception as e:
            attempt_log[-1]['error'] = str(e)
            offers = []

        if offers:
            # If whitelist present and priority set - reorder
            wl = trial_cfg.get('gpu_whitelist') or []
            if wl and trial_cfg.get('gpu_priority', True):
                offers = prioritize_offers_by_whitelist(offers, wl)
            attempt_log[-1]['found'] = len(offers)
            return offers, trial_cfg, attempt_log
        else:
            attempt_log[-1]['found'] = 0
            # continue to next modifier

    # nothing found
    return [], cfg, attempt_log


def main():
    parser = argparse.ArgumentParser(
        description='Run video processing on Vast.ai using config.yaml'
    )
    # Config is always loaded from the project root config.yaml
    parser.add_argument('--config', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    parser.add_argument('preset', nargs='?',
                        help='Preset name to use (matches keys in config.yaml presets: e.g. low, balanced, high, or a custom name). If omitted, uses vast.preset or balanced')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show configuration and search results without creating instance')
    parser.add_argument('--smoke-seconds', type=int, default=8,
                        help='Number of seconds to download for smoke-test on the remote instance (0 to disable)')
    parser.add_argument('--smoke-timeout', type=int, default=180,
                        help='Timeout in seconds for the remote smoke-test steps')
    parser.add_argument('--bucket', help='B2 bucket name (overrides B2_BUCKET env)')
    parser.add_argument('--input-url', help='Public HTTP(S) URL of the input file (overrides config.video.input and env)')
    parser.add_argument('--output', help='Output filename to use on B2 (overrides config.video.output)')
    parser.add_argument('--reuse-instance', help='Reuse host from this instance ID (finds host_id automatically)')

    args = parser.parse_args()

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config from {args.config}: {e}")
        sys.exit(1)

    # Extract settings
    video_config = config.get('video', {})
    # Per user request: never use `video.input` или `video.output` from config.yaml — игнорировать/удалять их, чтобы избежать случайного использования
    for _k in ('input', 'output'):
        if _k in video_config:
            try:
                video_config.pop(_k, None)
                print(f"Info: 'video.{_k}' in config.yaml will be ignored (per configuration policy).")
            except Exception:
                pass
    # vast_config теперь корректно выбирается через select_vast_config
    vast_config = select_vast_config(config, args.preset)
    advanced_config = config.get('advanced', {})

    # Handle --reuse-instance
    if args.reuse_instance:
        try:
            prev_info = vast_submit.get_instance(args.reuse_instance)
            if prev_info:
                reuse_host = prev_info.get('instances', {}).get('host_id')
                if reuse_host:
                    vast_config['reuse_host'] = int(reuse_host)
                    print(f"✓ Found host_id: {reuse_host} from instance {args.reuse_instance}")
                else:
                    print(f"⚠️  Could not get host_id from instance {args.reuse_instance}")
            else:
                print(f"⚠️  Instance {args.reuse_instance} not found")
        except Exception as e:
            print(f"⚠️  Error getting host info: {e}")

    if not vast_config:
        print("Error: 'vast' section not found in config and no presets available. Please add a 'vast' block or a 'presets' section.")
        sys.exit(1)

    preset = vast_config.get('preset', 'balanced')

    print(f"\n{'='*60}")
    print(f"🚀 Vast.ai Video Processing - Preset: {preset.upper()}")
    print(f"{'='*60}\n")

    # Display configuration
    print("📹 Video Settings:")
    print(f"  Input:      {video_config.get('input', 'N/A')}")
    print(f"  Output:     {video_config.get('output', 'N/A')}")
    print(f"  Mode:       {video_config.get('mode', 'both')}")
    print(f"  Scale:      {video_config.get('scale', 2)}x")
    print(f"  Target FPS: {video_config.get('target_fps', 60)}")

    print("\n🖥️  Instance Requirements:")
    print(f"  Min VRAM:   {vast_config.get('min_vram', 8)} GB")
    print(f"  Price:      ${vast_config.get('min_price', 0)} - ${vast_config.get('max_price', 0.50)}/hour")
    if 'gpu_models' in vast_config and vast_config.get('gpu_models'):
        print(f"  GPU Models: {', '.join(vast_config['gpu_models'])}")
    if 'gpu_whitelist' in vast_config and vast_config.get('gpu_whitelist'):
        print(f"  GPU Whitelist: {', '.join(vast_config['gpu_whitelist'])}")
    if 'gpu_blacklist' in vast_config and vast_config.get('gpu_blacklist'):
        print(f"  GPU Blacklist: {', '.join(vast_config['gpu_blacklist'])}")
    if 'min_reliability' in vast_config:
        try:
            rel = float(vast_config.get('min_reliability'))
            print(f"  Reliability: ≥{rel*100:.0f}%")
        except Exception:
            print(f"  Reliability: {vast_config.get('min_reliability')}")
    if 'min_dlperf' in vast_config:
        print(f"  DL Perf:    ≥{vast_config.get('min_dlperf')}")

    # Try searching with iterative fallback and whitelist prioritization
    print(f"\n🔍 Searching for offers (with fallback)...")
    offers, used_cfg, attempt_log = try_search_with_fallback(vast_config)

    # Print attempt log summary
    print("\n🧾 Search attempts summary:")
    for a in attempt_log:
        attempt_no = a.get('attempt')
        found = a.get('found', 0)
        err = a.get('error')
        print(f"  Attempt {attempt_no}: found={found}{'  ERROR='+err if err else ''}")

    if not offers:
        print("\n❌ No offers found after fallback attempts.")
        print("\n💡 Suggestions:")
        print("  - Increase max_price in preset 'presets' or vast.max_price")
        print("  - Decrease min_vram in preset")
        print("  - Remove gpu_models or set gpu_required=false")
        print("  - Lower min_reliability threshold")
        # show last used params for debugging
        print("\n🔧 Last used search params:")
        import json
        print(json.dumps(attempt_log[-1]['params'] if attempt_log else {}, indent=2))
        sys.exit(1)

    print(f"\n✅ Found {len(offers)} matching offers (using adjusted config: preset={used_cfg.get('preset')})\n")
    # use used_cfg as the effective vast_config
    vast_config = used_cfg

    # If user requested a disk hint (allocated_storage or min_disk), try to filter offers by reported disk size
    disk_hint = None
    if 'allocated_storage' in vast_config:
        disk_hint = vast_config.get('allocated_storage')
    elif 'min_disk' in vast_config:
        disk_hint = vast_config.get('min_disk')

    if disk_hint:
        try:
            dh = int(disk_hint)
            def _offer_disk_size(o: dict):
                # try common keys that may contain disk size in GB
                for k in ('disk', 'disk_gb', 'disk_size', 'storage', 'storage_gb', 'disk_size_gb', 'disk_space'):
                    v = o.get(k)
                    if v is None:
                        continue
                    try:
                        return int(float(v))
                    except Exception:
                        try:
                            # sometimes nested pricing/info fields
                            if isinstance(v, str) and v.endswith('GB'):
                                return int(float(v.replace('GB','').strip()))
                        except Exception:
                            continue
                return None

            orig_count = len(offers)
            offers_filtered = [o for o in offers if (_offer_disk_size(o) is None) or (_offer_disk_size(o) >= dh)]
            filtered_count = len(offers_filtered)
            if filtered_count == 0:
                print(f"⚠️  Disk filter requested ({dh} GB) but no offers report sufficient disk — keeping original offers (API may not expose disk size)")
            else:
                print(f"✓ Filtered offers by disk: required {dh} GB → {filtered_count}/{orig_count} offers remain")
                offers = offers_filtered
        except Exception as _:
            # non-fatal — proceed without disk filtering
            pass

    # If dry-run requested, stop here (do not create instance)
    if args.dry_run:
        print("\n🔍 Dry run - stopping here (no instance will be created)")
        return

    # Pick best offer
    chosen = vast_submit.pick_offer(offers)
    if not chosen:
        print("❌ Failed to pick an offer")
        sys.exit(1)

    print(f"\n✅ Selected: {vast_submit.human_offer_summary(chosen)}")

    # Check if we should reuse host
    reuse_host = vast_config.get('reuse_host')
    if reuse_host:
        print(f"♻️  Reusing host: {reuse_host}")
        # Filter offers to only this host
        offers = [o for o in offers if o.get('host_id') == int(reuse_host)]
        if not offers:
            print(f"❌ Host {reuse_host} not available")
            sys.exit(1)
        chosen = offers[0]

    # Upload input to B2
    # Determine input source (config.video.input is ignored by policy)
    input_file = None
    if args.input_url:
        input_file = args.input_url
    elif os.environ.get('INPUT_URL'):
        input_file = os.environ.get('INPUT_URL')
    elif os.environ.get('VIDEO_INPUT_URL'):
        input_file = os.environ.get('VIDEO_INPUT_URL')

    if not input_file:
        print("❌ No input provided. Per policy, 'video.input' in config.yaml is ignored.")
        # Diagnostic details: what we checked
        checked = []
        if args.input_url:
            checked.append("--input-url")
        if os.environ.get('INPUT_URL'):
            checked.append('INPUT_URL env')
        if os.environ.get('VIDEO_INPUT_URL'):
            checked.append('VIDEO_INPUT_URL env')
        if checked:
            print(f"Checked sources but none provided usable input: {', '.join(checked)}")
        else:
            print("Checked sources: --input-url, INPUT_URL env, VIDEO_INPUT_URL env — none present.")

        if video_config.get('input_dir'):
            print(f"Note: config.yaml contains batch directory: video.input_dir = '{video_config.get('input_dir')}'")
            print("This script runs in single-input mode; to process a B2 directory use scripts/run_with_config_batch_sync.py or supply a single input with --input-url or INPUT_URL env.")
        else:
            print("No batch input directory (video.input_dir) found in config.yaml either.")

        print("Remedies:")
        print("  1) Run batch processing: python scripts/run_with_config_batch_sync.py (reads video.input_dir from config)")
        print("  2) Supply a single input URL: run run_with_config.py --input-url <http(s)-url-or-s3-path> ")
        print("  3) Export environment variable: export INPUT_URL=<url> (or set in .env)")
        sys.exit(1)

    bucket = os.environ.get('B2_BUCKET', 'noxfvr-videos')
    input_key = f"input/{Path(input_file).name}"

    # Determine output name: priority -> CLI --output -> ENV OUTPUT_NAME/OUTPUT_FILENAME -> derive from input filename
    if args.output:
        output_name = Path(args.output).name
    elif os.environ.get('OUTPUT_NAME') or os.environ.get('OUTPUT_FILENAME'):
        output_name = Path(os.environ.get('OUTPUT_NAME') or os.environ.get('OUTPUT_FILENAME')).name
    else:
        # derive from input filename (use stem + .mp4)
        output_name = f"{Path(input_file).stem}.mp4"

    try:
        # support video.append_timestamp boolean in config (still allowed)
        if isinstance(video_config.get('append_timestamp'), bool) and video_config.get('append_timestamp'):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            stem = Path(output_name).stem
            suffix = Path(output_name).suffix or '.mp4'
            output_name = f"{stem}_{ts}{suffix}"
    except Exception:
        pass

    output_key = f"output/{output_name}"

    # Determine whether input is local or already on B2 / HTTP / S3
    input_url = None
    is_local_input = False

    if os.path.exists(input_file):
        is_local_input = True
    else:
        # Recognize full HTTP(S) URL
        if str(input_file).startswith(('http://', 'https://')):
            input_url = input_file
        # s3://bucket/key or b2://bucket/key -> map to B2 HTTP endpoint
        elif str(input_file).startswith(('s3://', 'b2://')):
            proto, rest = str(input_file).split('://', 1)
            parts = rest.split('/', 1)
            if len(parts) == 2:
                bucket_from_input, key_from_input = parts
                b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')
                input_url = f"{b2_endpoint.rstrip('/')}/{bucket_from_input}/{key_from_input.lstrip('/')}"
            else:
                print(f"❌ Invalid S3/B2 path: {input_file}")
                sys.exit(1)
        else:
            # Treat any non-local, non-URL input as a key in the default bucket on B2
            # Support both 'input/kk3.mp4' and 'kk3.mp4'
            b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')
            key_guess = str(input_file).lstrip('/')
            # If user provided a path-like value, keep it; otherwise assume key at bucket root
            input_url = f"{b2_endpoint.rstrip('/')}/{bucket}/{key_guess}"
            print(f"Assuming input is on B2 at: {input_url}")

    print(f"\n📤 Preparing input URL (local_upload={is_local_input})")
    try:
        from scripts.run_slim_vast import upload_to_b2, generate_output_presigned_url
        if is_local_input:
            print(f"\n📤 Uploading {input_file} to B2...")
            b2_info = upload_to_b2(input_file, bucket, input_key)
            input_url = b2_info['get_url']
            print(f"✓ Uploaded / found on B2: {input_url}")
        else:
            print(f"✓ Using remote input URL: {input_url}")

        # Generate output presigned URL
        output_put_url, output_get_url = generate_output_presigned_url(bucket, output_key)
    except Exception as e:
        print(f"❌ Error preparing input/output URLs: {e}")
        sys.exit(1)

    # Now input_url is a HTTP(S) GET URL usable by the remote container

    # Build container command
    print(f"\n🐳 Preparing container command...")
    from scripts.run_slim_vast import build_container_command

    mode = video_config.get('mode', 'both')
    scale = video_config.get('scale', 2)
    target_fps = video_config.get('target_fps', 60)
    prefer = advanced_config.get('prefer', 'auto')
    strict = advanced_config.get('strict', False)

    # Get B2 credentials
    b2_key = os.environ.get('B2_KEY')
    b2_secret = os.environ.get('B2_SECRET')
    bucket = args.bucket or os.environ.get('B2_BUCKET', 'noxfvr-videos')
    b2_endpoint = os.environ.get('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com')

    if not b2_key or not b2_secret:
        print("❌ B2_KEY and B2_SECRET environment variables required")
        sys.exit(1)

    # RIFE model URL (optional) - can be set globally or under vast preset
    rife_model_url = None
    if 'rife_model_url' in config:
        rife_model_url = config.get('rife_model_url')
    if 'rife_model_url' in vast_config:
        rife_model_url = vast_config.get('rife_model_url')

    # Export min_vram hint so build_container_command can auto-generate BATCH_ARGS
    try:
        # Prefer actual chosen offer GPU RAM if available (gpu_ram in MB), else fall back to preset min_vram
        gpu_ram_mb = None
        try:
            gpu_ram_mb = int(chosen.get('gpu_ram')) if chosen and chosen.get('gpu_ram') else None
        except Exception:
            gpu_ram_mb = None
        if gpu_ram_mb:
            # Use ceiling division so 9977 MB -> 10 GB (more appropriate for heuristics)
            gb_ceil = max(1, (int(gpu_ram_mb) + 1023) // 1024)
            os.environ['VAST_MIN_VRAM'] = str(gb_ceil)
        else:
            os.environ['VAST_MIN_VRAM'] = str(vast_config.get('min_vram', 8))
    except Exception:
        pass

    cmd = build_container_command(
        input_url, mode, scale, target_fps,
        bucket, b2_key, b2_secret, b2_endpoint, output_key,
        prefer, strict,
        smoke_seconds=args.smoke_seconds,
        smoke_timeout=args.smoke_timeout,
        rife_model_url=rife_model_url
    )

    # Create instance
    image = config.get('image', 'registry.gitlab.com/gfever/vastai_interup:pytorch-fat-07110957')
    wait_finish = vast_config.get('wait', False)

    print(f"\n🚀 Creating instance...")
    print(f"   Image: {image}")
    print(f"   Wait for completion: {wait_finish}")

    try:
        from scripts.run_slim_vast import create_vast_instance
        # Determine disk allocation hint (prefer explicit allocated_storage, fallback to min_disk)
        disk_hint = None
        if 'allocated_storage' in vast_config:
            disk_hint = vast_config.get('allocated_storage')
        elif 'min_disk' in vast_config:
            disk_hint = vast_config.get('min_disk')

        result = create_vast_instance(
            image=image,
            cmd=cmd,
            min_vram=vast_config.get('min_vram', 8),
            max_price=vast_config.get('max_price', 0.50),
            wait_finish=wait_finish,
            reuse_host_id=reuse_host,
            input_get_url=input_url,
            min_price=vast_config.get('min_price'),
            gpu_name=None,  # Already filtered by search
            disk_gb=disk_hint
        )

        instance_id = result.get('instance_id')
        if instance_id:
            print(f"\n✅ Instance created: {instance_id}")
            print(f"   Monitor: https://cloud.vast.ai/instances/")

            # Save instance info for reuse
            reuse_file = Path(__file__).parent.parent / '.last_instance'
            with open(reuse_file, 'w') as f:
                f.write(f"{instance_id}\n")
            print(f"   Saved to: {reuse_file} (for quick reuse)")

        if vast_config.get('download', True) and not wait_finish:
            print(f"\n💡 To download output later:")
            print(f"   wget '{output_get_url}' -O {output_name}")

        if wait_finish and vast_config.get('download', True):
            print(f"\n📥 Downloading output...")
            from scripts.run_slim_vast import download_from_b2
            download_from_b2(output_get_url, output_name)
            print(f"✅ Done! Output saved to: {output_name}")

    except Exception as e:
        print(f"❌ Error creating instance: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
