#!/usr/bin/env python3
"""
Quick test to verify Real-ESRGAN native processor logging improvements.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

logger.info("Testing Real-ESRGAN native processor logging...")

try:
    from infrastructure.processors.realesrgan.native import RealESRGANNative, GPUMemoryDetector

    # Test GPU detection
    logger.info("Testing GPU memory detection...")
    memories = GPUMemoryDetector.get_gpu_memory_mb()
    if memories:
        logger.info(f"✓ Found {len(memories)} GPU(s): {memories} MB")
        batch_size = GPUMemoryDetector.suggest_batch_size(memories[0] if memories else None)
        logger.info(f"✓ Suggested batch size: {batch_size}")
    else:
        logger.info("⚠ No GPUs detected (may be running on CPU)")
        batch_size = 1

    # Create processor (will not load model, just test initialization)
    logger.info("Creating Real-ESRGAN processor...")
    processor = RealESRGANNative(
        scale=2,
        tile_size=512,
        batch_size=batch_size,
        logger=logger
    )
    logger.info(f"✓ Processor created successfully")
    logger.info(f"  Scale: {processor.scale}x")
    logger.info(f"  Tile size: {processor.tile_size}")
    logger.info(f"  Batch size: {processor.batch_size}")
    logger.info(f"  Device: {processor.device}")

    logger.info("✅ All tests passed!")

except Exception as e:
    logger.error(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

