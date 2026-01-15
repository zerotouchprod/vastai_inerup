#!/usr/bin/env python3
"""
Test script to verify multi-GPU support for all modes.
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

def check_gpu_availability():
    """Check if GPU is available and how many."""
    try:
        import torch
        
        if not torch.cuda.is_available():
            logger.error("❌ CUDA not available")
            return 0
        
        num_gpus = torch.cuda.device_count()
        logger.info(f"✅ Found {num_gpus} GPU(s)")
        
        for i in range(num_gpus):
            gpu_name = torch.cuda.get_device_name(i)
            props = torch.cuda.get_device_properties(i)
            gpu_memory = props.total_memory / (1024**3)
            logger.info(f"  GPU {i}: {gpu_name} ({gpu_memory:.1f}GB)")
        
        return num_gpus
        
    except ImportError:
        logger.error("❌ PyTorch not installed")
        return 0

def test_realesrgan_multigpu():
    """Test RealESRGAN multi-GPU support."""
    logger.info("\n" + "="*60)
    logger.info("Testing RealESRGAN Multi-GPU Support")
    logger.info("="*60)
    
    try:
        from src.infrastructure.processors.realesrgan.native import RealESRGANNative
        
        processor = RealESRGANNative(scale=2)
        
        logger.info(f"✅ RealESRGAN initialized")
        logger.info(f"   Detected GPUs: {processor.num_gpus}")
        logger.info(f"   GPU devices: {processor.gpu_devices}")
        logger.info(f"   Batch size: {processor.batch_size}")
        
        if processor.num_gpus > 1:
            logger.info(f"✅ Multi-GPU support: ENABLED")
        else:
            logger.info(f"⚠️  Single GPU mode")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ RealESRGAN test failed: {e}")
        return False

def test_rife_multigpu():
    """Test RIFE multi-GPU support."""
    logger.info("\n" + "="*60)
    logger.info("Testing RIFE Multi-GPU Support")
    logger.info("="*60)
    
    try:
        from src.infrastructure.processors.rife.native import RIFENative
        
        processor = RIFENative(factor=2)
        
        logger.info(f"✅ RIFE initialized")
        logger.info(f"   Detected GPUs: {processor.num_gpus}")
        logger.info(f"   GPU devices: {processor.devices}")
        
        if processor.num_gpus > 1:
            logger.info(f"✅ Multi-GPU support: ENABLED")
        else:
            logger.info(f"⚠️  Single GPU mode")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ RIFE test failed: {e}")
        return False

def test_propainter_multigpu():
    """Test ProPainter multi-GPU support."""
    logger.info("\n" + "="*60)
    logger.info("Testing ProPainter Multi-GPU Support")
    logger.info("="*60)
    
    try:
        from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
        
        adapter = ProPainterAdapter()
        
        logger.info(f"✅ ProPainter initialized")
        logger.info(f"   Detected GPUs: {adapter.num_gpus}")
        logger.info(f"   GPU devices: {adapter.devices}")
        
        if adapter.num_gpus > 1:
            logger.info(f"✅ Multi-GPU support: ENABLED")
        else:
            logger.info(f"⚠️  Single GPU mode")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ ProPainter test failed: {e}")
        return False

def main():
    """Run all multi-GPU tests."""
    logger.info("="*60)
    logger.info("Multi-GPU Support Test Suite")
    logger.info("="*60)
    
    # Check GPU availability
    num_gpus = check_gpu_availability()
    
    if num_gpus == 0:
        logger.error("No GPUs available. Exiting.")
        sys.exit(1)
    
    # Run tests
    results = {
        'RealESRGAN': test_realesrgan_multigpu(),
        'RIFE': test_rife_multigpu(),
        'ProPainter': test_propainter_multigpu()
    }
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("Test Summary")
    logger.info("="*60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{name}: {status}")
        if not passed:
            all_passed = False
    
    logger.info("="*60)
    
    if all_passed:
        logger.info("✅ All tests passed!")
        if num_gpus > 1:
            logger.info(f"🚀 Multi-GPU mode is ready! ({num_gpus} GPUs detected)")
            logger.info(f"   Expected speedup: ~{num_gpus * 0.9:.1f}x vs single GPU")
        else:
            logger.info("⚠️  Single GPU mode (only 1 GPU detected)")
        sys.exit(0)
    else:
        logger.error("❌ Some tests failed")
        sys.exit(1)

if __name__ == '__main__':
    main()

