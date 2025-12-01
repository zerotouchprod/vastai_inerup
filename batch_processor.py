#!/usr/bin/env python3
"""
Unified Batch Processor for Vast.ai

This script replaces:
- run_with_config_batch_sync.py
- run_with_config_batch.py
- run_with_config.py
- run_slim_vast.py

Usage:
    # Process single file
    python batch_processor.py --input video.mp4

    # Process directory from B2
    python batch_processor.py --input-dir input/batch1

    # Process with config
    python batch_processor.py --config config.yaml --input-dir input/batch1

    # Dry run (show what would be processed)
    python batch_processor.py --input-dir input/batch1 --dry-run
"""

import os
import sys
import argparse
import yaml
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use system env vars

# Add src to path
_SRC_DIR = Path(__file__).parent / 'src'
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from domain.b2_storage import B2Credentials, B2Object
    from domain.vastai import VastInstanceConfig
    from infrastructure.storage.b2_client import B2Client
    from infrastructure.vastai.client import VastAIClient
    from shared.logging import get_logger
    from shared.remote_config import load_config_with_remote

    # Get logger
    logger = get_logger(__name__)
except ImportError as e:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)
    logger.error(f"Failed to import modules: {e}")
    logger.error("Make sure you're running from project root")
    sys.exit(1)


class BatchProcessor:
    """
    Unified batch processor for Vast.ai video processing.

    Handles:
    - Single file processing
    - Batch directory processing
    - Vast.ai instance management
    - B2 storage integration
    """

    def __init__(self, config_path: str = 'config.yaml'):
        """
        Initialize batch processor.

        Args:
            config_path: Path to config file
        """
        self.config_path = config_path
        self.config = self._load_config()


        # Initialize clients
        self.b2_client = None
        self.vast_client = None

        self._init_clients()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file and merge with remote config if config_url is set."""
        return load_config_with_remote(Path(self.config_path), logger_instance=logger)

    def _init_clients(self):
        """Initialize B2 and Vast.ai clients."""
        try:
            # B2 client
            b2_creds = B2Credentials.from_env()
            if b2_creds.validate():
                self.b2_client = B2Client(b2_creds)
                logger.info("[OK] B2 client initialized")
            else:
                logger.warning("[WARN] B2 credentials not set (B2_KEY, B2_SECRET, B2_BUCKET)")

        except Exception as e:
            logger.error(f"Failed to initialize B2 client: {e}")

        try:
            # Vast.ai client
            self.vast_client = VastAIClient()
            logger.info("[OK] Vast.ai client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Vast.ai client: {e}")

    def list_input_files(
        self,
        input_dir: str,
        skip_existing: bool = True
    ) -> List['B2Object']:
        """
        List video files from B2 input directory.

        Args:
            input_dir: Input directory in B2
            skip_existing: Skip files that already have output

        Returns:
            List of B2Object instances
        """
        if not self.b2_client:
            raise RuntimeError("B2 client not initialized")

        # Build prefix
        prefix = input_dir if input_dir.startswith('input/') else f'input/{input_dir}'

        logger.info(f"[LIST] Listing files from B2: {prefix}")

        # List objects
        objects = self.b2_client.list_objects(prefix=prefix)

        # Filter video files
        video_extensions = ('.mp4', '.mkv', '.mov', '.avi', '.webm')
        video_files = [
            obj for obj in objects
            if obj.key.lower().endswith(video_extensions) and obj.size > 0
        ]

        logger.info(f"[OK] Found {len(video_files)} video files")

        # Skip existing outputs if requested
        if skip_existing:
            video_files = self._filter_existing_outputs(video_files)

        return video_files

    def _monitor_processing(self, instance_id: int, timeout: int = 7200) -> Optional[str]:
        """
        Monitor instance processing and extract result URL.

        Args:
            instance_id: Instance ID to monitor
            timeout: Maximum time to wait in seconds

        Returns:
            Result URL if found, None otherwise
        """
        import time
        import re

        start_time = time.time()
        last_log_line = 0
        success_marker = "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
        url_pattern = r'https://[^\s]+'

        logger.info(f"[MONITOR] Watching logs for instance #{instance_id}...")

        consecutive_failures = 0
        max_consecutive_failures = 6  # 6 failures = 1 minute of no response
        check_count = 0

        while time.time() - start_time < timeout:
            try:
                check_count += 1
                elapsed = int(time.time() - start_time)

                # Progress indicator every 30 seconds
                if check_count % 6 == 0:
                    logger.info(f"[MONITOR] Still monitoring... ({elapsed}s elapsed, {len(lines) if 'lines' in locals() else 0} log lines)")

                # Get logs
                logs = self.vast_client.get_instance_logs(instance_id, tail=500)

                if not logs:
                    consecutive_failures += 1
                    if consecutive_failures == 1:
                        logger.info(f"[MONITOR] Waiting for logs to appear...")
                    elif consecutive_failures >= max_consecutive_failures:
                        logger.warning(f"[WARN] No logs after {consecutive_failures * 10}s, but continuing...")
                        consecutive_failures = 0  # Reset to avoid spam
                    time.sleep(10)
                    continue

                # Reset failure counter on success
                consecutive_failures = 0

                lines = logs.split('\n')

                # Show new lines (only if there are actually new lines)
                if len(lines) > last_log_line:
                    new_lines = lines[last_log_line:]
                    new_content = [line for line in new_lines if line.strip()]

                    if new_content:
                        for line in new_content:
                            logger.info(f"  [LOG] {line}")
                        last_log_line = len(lines)

                # Check for success
                if success_marker in logs:
                    logger.info(f"[OK] Processing completed successfully!")

                    # Extract result URL
                    urls = re.findall(url_pattern, logs)
                    for url in reversed(urls):  # Get last URL
                        if 'noxfvr-videos' in url and ('output/' in url or 'both/' in url or 'upscales/' in url or 'interps/' in url):
                            logger.info(f"[RESULT] Download URL: {url}")
                            return url

                    logger.warning("[WARN] Success marker found but no result URL")
                    return None

                # Check for errors (only report once)
                if check_count == 1 or (check_count % 12 == 0):  # Check every 2 minutes
                    if 'ERROR' in logs or 'FAILED' in logs:
                        error_lines = [l for l in lines if 'ERROR' in l or 'FAILED' in l]
                        if error_lines:
                            logger.warning(f"[WARN] Recent errors: {error_lines[-1][:100]}")

                time.sleep(10)

            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures <= 3:  # Only log first 3 failures
                    logger.warning(f"[WARN] Log fetch failed (attempt {consecutive_failures}): {e}")
                time.sleep(10)

        logger.error(f"[ERROR] Monitoring timeout after {timeout}s")
        return None

    def _filter_existing_outputs(self, files: List) -> List:
        """Filter out files that already have output."""
        if not self.b2_client:
            return files

        try:
            # List existing outputs
            output_objects = self.b2_client.list_objects(prefix='output/')
            existing_stems = {obj.stem for obj in output_objects}

            # Filter
            filtered = []
            skipped = 0

            for file_obj in files:
                stem = file_obj.stem
                if stem in existing_stems:
                    logger.info(f"[WARN] Skipping {file_obj.key} - output exists")
                    skipped += 1
                else:
                    filtered.append(file_obj)

            if skipped > 0:
                logger.info(f"Skipped {skipped} files with existing outputs")

            return filtered

        except Exception as e:
            logger.warning(f"Could not check existing outputs: {e}")
            return files

    def process_single_file(
        self,
        input_url: str,
        output_name: Optional[str] = None,
        preset: str = 'balanced'
    ) -> Dict[str, Any]:
        """
        Process single file on Vast.ai.

        Args:
            input_url: Input file URL
            output_name: Output file name (auto-generated if None)
            preset: Preset name from config

        Returns:
            Processing result dict
        """
        if not self.vast_client:
            raise RuntimeError("Vast.ai client not initialized")

        # Generate output name if not provided
        if not output_name:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_name = f"output_{timestamp}.mp4"

        logger.info(f"[RUN] Processing file: {input_url}")
        logger.info(f"   Output: {output_name}")
        logger.info(f"   Preset: {preset}")

        # Get preset config
        preset_config = self.config.get('presets', {}).get(preset, {})
        if not preset_config:
            raise ValueError(f"Preset not found: {preset}")

        # Search for offers
        offers = self.vast_client.search_offers(
            min_vram_gb=preset_config.get('min_vram', 12),
            max_price=preset_config.get('max_price', 0.5),
            min_reliability=preset_config.get('min_reliability', 0.9),
            limit=10,
            host_whitelist=preset_config.get('host_whitelist'),
            host_blacklist=preset_config.get('host_blacklist')
        )

        if not offers:
            raise RuntimeError("No suitable offers found")

        # Use best offer (first one - already sorted by price)
        offer = offers[0]
        logger.info(f"[OK] Selected offer: {offer}")

        # Build instance config
        video_config = self.config.get('video', {})

        # Get git repo URL and branch from config
        git_repo = self.config.get('git_repo', 'https://github.com/zerotouchprod/vastai_inerup.git')
        git_branch = self.config.get('git_branch', 'main')
        
        # Build onstart command that clones repo and runs script
        # Remove old project dir first to avoid "already exists" error
        onstart_cmd = (
            f"cd /workspace && "
            f"rm -rf project && "
            f"git clone -b {git_branch} {git_repo} project && "
            f"cd project && "
            f"bash scripts/remote_runner.sh"
        )

        instance_config = VastInstanceConfig(
            image=self.config.get('image', ''),
            disk=50,
            env={
                'INPUT_URL': input_url,
                'B2_OUTPUT_KEY': f"output/{output_name}",
                'B2_BUCKET': os.getenv('B2_BUCKET', ''),
                'B2_KEY': os.getenv('B2_KEY', ''),
                'B2_SECRET': os.getenv('B2_SECRET', ''),
                'B2_ENDPOINT': os.getenv('B2_ENDPOINT', 'https://s3.us-west-004.backblazeb2.com'),
                'MODE': video_config.get('mode', 'both'),
                'SCALE': str(video_config.get('scale', 2)),
                'TARGET_FPS': str(video_config.get('target_fps', 60)),
                'USE_NATIVE_PROCESSORS': '1',  # Use new Python code!
            },
            onstart=onstart_cmd,
            label=f"video_processing_{output_name}",
        )

        # Create instance
        instance = self.vast_client.create_instance(offer.id, instance_config)
        logger.info(f"[OK] Created instance: {instance}")

        # Wait for running
        try:
            instance = self.vast_client.wait_for_running(
                instance.id,
                timeout=300,
                poll_interval=10
            )
            logger.info(f"[OK] Instance running: {instance}")
        except TimeoutError as e:
            logger.error(f"Instance failed to start: {e}")
            raise

        # Monitor processing
        logger.info(f"[MONITOR] Monitoring instance #{instance.id} for completion...")
        result_url = self._monitor_processing(instance.id, timeout=7200)  # 2 hours max

        # Destroy instance
        logger.info(f"[CLEANUP] Destroying instance #{instance.id}...")
        self.vast_client.destroy_instance(instance.id)
        logger.info(f"[OK] Instance destroyed")

        return {
            'instance_id': instance.id,
            'input_url': input_url,
            'output_name': output_name,
            'result_url': result_url,
            'status': 'completed' if result_url else 'failed'
        }

    def process_batch(
        self,
        input_dir: str,
        preset: str = 'balanced',
        dry_run: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Process batch of files from B2 directory.

        Args:
            input_dir: Input directory in B2
            preset: Preset name from config
            dry_run: If True, only show what would be processed

        Returns:
            List of processing results
        """
        # List files
        files = self.list_input_files(input_dir)

        if not files:
            logger.info("No files to process")
            return []

        logger.info(f"[STAT] {len(files)} files to process")

        if dry_run:
            logger.info("[DRY] Dry run - not creating instances")
            for idx, file_obj in enumerate(files, 1):
                logger.info(f"  {idx}. {file_obj.key} ({file_obj.size} bytes)")
            return []

        # Process each file
        results = []

        for idx, file_obj in enumerate(files, 1):
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing file {idx}/{len(files)}")
            logger.info(f"{'='*60}\n")

            try:
                # Get presigned URL
                input_url = self.b2_client.get_presigned_url(
                    file_obj.key,
                    expires_in=7200  # 2 hours
                )

                # Generate output name
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_name = f"{file_obj.stem}_{timestamp}.mp4"

                # Process
                result = self.process_single_file(
                    input_url=input_url,
                    output_name=output_name,
                    preset=preset
                )

                results.append(result)
                logger.info(f"[OK] File {idx}/{len(files)} submitted")

            except Exception as e:
                logger.error(f"[ERROR] Failed to process {file_obj.key}: {e}")
                import traceback
                traceback.print_exc()
                continue

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Unified Batch Processor for Vast.ai - reads defaults from config.yaml'
    )

    parser.add_argument('--config', default='config.yaml',
                       help='Config file (default: config.yaml)')
    parser.add_argument('--input', help='Single input file URL (overrides config)')
    parser.add_argument('--input-dir', help='Input directory in B2 (overrides config)')
    parser.add_argument('--output', help='Output file name (for single file)')
    parser.add_argument('--preset', help='Preset name (overrides config)')
    parser.add_argument('--dry-run', action='store_true', default=None,
                       help='Show what would be processed (overrides config)')
    parser.add_argument('--skip-existing', action='store_true', default=None,
                       help='Skip files with existing output (overrides config)')

    args = parser.parse_args()

    try:
        # Initialize processor
        processor = BatchProcessor(config_path=args.config)

        # Get batch config from config.yaml
        batch_config = processor.config.get('batch', {})
        video_config = processor.config.get('video', {})

        # Determine input source (CLI args override config)
        input_url = args.input
        # Priority: CLI > video.input_dir (remote) > batch.input_dir (local)
        # Remote config should override local config
        input_dir = args.input_dir or video_config.get('input_dir') or batch_config.get('input_dir')
        preset = args.preset or batch_config.get('preset', 'balanced')
        dry_run = args.dry_run if args.dry_run is not None else batch_config.get('dry_run', False)
        skip_existing = args.skip_existing if args.skip_existing is not None else batch_config.get('skip_existing', True)

        # Validate: need either input or input_dir
        if not input_url and not input_dir:
            logger.error("[ERROR] No input specified!")
            logger.error("Either:")
            logger.error("  1. Set 'batch.input_dir' in config.yaml")
            logger.error("  2. Use --input <url> for single file")
            logger.error("  3. Use --input-dir <dir> for batch")
            sys.exit(1)

        # Validate credentials before processing
        if input_dir and not processor.b2_client:
            logger.error("[ERROR] B2 client not initialized - cannot list files from B2")
            logger.error("Please set environment variables:")
            logger.error("  $env:B2_KEY='your_key_id'")
            logger.error("  $env:B2_SECRET='your_application_key'")
            logger.error("  $env:B2_BUCKET='noxfvr-videos'")
            sys.exit(1)

        if not processor.vast_client:
            logger.error("[ERROR] Vast.ai client not initialized - cannot create instances")
            logger.error("Please set environment variable:")
            logger.error("  $env:VAST_API_KEY='your_vast_api_key'")
            sys.exit(1)

        # Process
        if input_url:
            # Single file
            logger.info(f"[FILE] Processing single file: {input_url}")
            result = processor.process_single_file(
                input_url=input_url,
                output_name=args.output,
                preset=preset
            )
            logger.info(f"\n[OK] Processing submitted: {result}")

        elif input_dir:
            # Batch
            logger.info(f"[DIR] Processing batch from: {input_dir}")
            logger.info(f"[CFG] Preset: {preset}")
            logger.info(f"[DRY] Dry run: {dry_run}")
            logger.info(f"[SKIP] Skip existing: {skip_existing}\n")

            results = processor.process_batch(
                input_dir=input_dir,
                preset=preset,
                dry_run=dry_run
            )
            logger.info(f"\n[OK] Batch processing complete: {len(results)} files submitted")

    except Exception as e:
        logger.error(f"\n[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

