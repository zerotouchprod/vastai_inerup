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
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

# Add src to path
_SRC_DIR = Path(__file__).parent / 'src'
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

try:
    from domain.b2_storage import B2Credentials, B2Object
    from domain.vastai import VastInstanceConfig
    from infrastructure.storage.b2_client import B2Client
    from infrastructure.vastai.client import VastAIClient
    from shared.logging import setup_logging, get_logger
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

        # Setup logging
        setup_logging()

        # Initialize clients
        self.b2_client = None
        self.vast_client = None

        self._init_clients()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not Path(self.config_path).exists():
            raise FileNotFoundError(f"Config not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        return config

    def _init_clients(self):
        """Initialize B2 and Vast.ai clients."""
        try:
            # B2 client
            b2_creds = B2Credentials.from_env()
            if b2_creds.validate():
                self.b2_client = B2Client(b2_creds)
                logger.info("✓ B2 client initialized")
            else:
                logger.warning("⚠ B2 credentials not set (B2_KEY, B2_SECRET, B2_BUCKET)")

        except Exception as e:
            logger.error(f"Failed to initialize B2 client: {e}")

        try:
            # Vast.ai client
            self.vast_client = VastAIClient()
            logger.info("✓ Vast.ai client initialized")
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

        logger.info(f"📂 Listing files from B2: {prefix}")

        # List objects
        objects = self.b2_client.list_objects(prefix=prefix)

        # Filter video files
        video_extensions = ('.mp4', '.mkv', '.mov', '.avi', '.webm')
        video_files = [
            obj for obj in objects
            if obj.key.lower().endswith(video_extensions) and obj.size > 0
        ]

        logger.info(f"✓ Found {len(video_files)} video files")

        # Skip existing outputs if requested
        if skip_existing:
            video_files = self._filter_existing_outputs(video_files)

        return video_files

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
                    logger.info(f"⚠ Skipping {file_obj.key} - output exists")
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

        logger.info(f"🚀 Processing file: {input_url}")
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
            limit=10
        )

        if not offers:
            raise RuntimeError("No suitable offers found")

        # Use best offer (first one - already sorted by price)
        offer = offers[0]
        logger.info(f"✓ Selected offer: {offer}")

        # Build instance config
        video_config = self.config.get('video', {})

        instance_config = VastInstanceConfig(
            image=self.config.get('image', ''),
            disk=50,
            env={
                'INPUT_URL': input_url,
                'B2_OUTPUT_KEY': f"output/{output_name}",
                'B2_BUCKET': os.getenv('B2_BUCKET', ''),
                'B2_KEY': os.getenv('B2_KEY', ''),
                'B2_SECRET': os.getenv('B2_SECRET', ''),
                'MODE': video_config.get('mode', 'both'),
                'SCALE': str(video_config.get('scale', 2)),
                'TARGET_FPS': str(video_config.get('target_fps', 60)),
                'USE_NATIVE_PROCESSORS': '1',  # Use new Python code!
            },
            onstart='bash /workspace/project/scripts/remote_runner.sh',
            label=f"video_processing_{output_name}",
        )

        # Create instance
        instance = self.vast_client.create_instance(offer.id, instance_config)
        logger.info(f"✓ Created instance: {instance}")

        # Wait for running
        try:
            instance = self.vast_client.wait_for_running(
                instance.id,
                timeout=300,
                poll_interval=10
            )
            logger.info(f"✓ Instance running: {instance}")
        except TimeoutError as e:
            logger.error(f"Instance failed to start: {e}")
            raise

        return {
            'instance_id': instance.id,
            'input_url': input_url,
            'output_name': output_name,
            'offer': str(offer),
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

        logger.info(f"📊 {len(files)} files to process")

        if dry_run:
            logger.info("🔍 Dry run - not creating instances")
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
                logger.info(f"✓ File {idx}/{len(files)} submitted")

            except Exception as e:
                logger.error(f"❌ Failed to process {file_obj.key}: {e}")
                import traceback
                traceback.print_exc()
                continue

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Unified Batch Processor for Vast.ai'
    )

    parser.add_argument('--config', default='config.yaml',
                       help='Config file (default: config.yaml)')
    parser.add_argument('--input', help='Single input file URL')
    parser.add_argument('--input-dir', help='Input directory in B2')
    parser.add_argument('--output', help='Output file name (for single file)')
    parser.add_argument('--preset', default='balanced',
                       help='Preset name (default: balanced)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be processed')
    parser.add_argument('--skip-existing', action='store_true', default=True,
                       help='Skip files with existing output (default: True)')

    args = parser.parse_args()

    # Validate arguments
    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir required")

    try:
        # Initialize processor
        processor = BatchProcessor(config_path=args.config)

        # Process
        if args.input:
            # Single file
            result = processor.process_single_file(
                input_url=args.input,
                output_name=args.output,
                preset=args.preset
            )
            logger.info(f"\n✅ Processing submitted: {result}")

        elif args.input_dir:
            # Batch
            results = processor.process_batch(
                input_dir=args.input_dir,
                preset=args.preset,
                dry_run=args.dry_run
            )
            logger.info(f"\n✅ Batch processing complete: {len(results)} files submitted")

    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

