#!/usr/bin/env python3
"""
Pre-download PaddleOCR models for faster startup.
Improved version with better logging and model verification.
"""

import os
import sys
import logging
import time
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_existing_models():
    """Check if models are already downloaded."""
    model_dir = Path.home() / '.paddlex' / 'official_models'
    if model_dir.exists():
        model_files = list(model_dir.rglob('*.pdparams'))
        model_files += list(model_dir.rglob('*.pdiparams'))
        model_files += list(model_dir.rglob('*.pdmodel'))
        
        if model_files:
            total_size = sum(f.stat().st_size for f in model_files)
            logger.info(f"Found {len(model_files)} existing model files in {model_dir}")
            logger.info(f"Total size: {total_size / 1024**2:.1f} MB")
            return True, model_dir, len(model_files)
    
    return False, model_dir, 0

def main():
    start_time = time.time()
    
    # Check existing models first
    has_models, model_dir, file_count = check_existing_models()
    
    if has_models and file_count >= 20:  # PaddleOCR has many small files
        logger.info("✓ PaddleOCR models already exist. Skipping download.")
        logger.info(f"Model directory: {model_dir}")
        return True
    
    # Set environment variables before importing paddle
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    os.environ['LOG_LEVEL'] = 'ERROR'
    
    try:
        logger.info("Importing PaddleOCR...")
        from paddleocr import PaddleOCR
        
        # Try to use tqdm for progress if available
        try:
            from tqdm import tqdm
            use_tqdm = True
        except ImportError:
            use_tqdm = False
            logger.info("tqdm not available, using simple logging")
        
        logger.info("Initializing PaddleOCR English model...")
        
        # Initialize with minimal settings
        # Disable MKL-DNN to avoid illegal instruction errors on some CPUs
        ocr = PaddleOCR(
            lang='en',
            use_angle_cls=False,
            enable_mkldnn=False  # Disable MKL-DNN to avoid CPU compatibility issues
        )
        
        logger.info("✓ PaddleOCR English model initialized")
        
        # Also initialize Russian model if needed
        logger.info("Initializing PaddleOCR Russian model...")
        ocr_ru = PaddleOCR(
            lang='ru',
            use_angle_cls=False,
            enable_mkldnn=False  # Disable MKL-DNN
        )
        logger.info("✓ PaddleOCR Russian model initialized")
        
        # Verify models were downloaded
        has_models_after, model_dir_after, file_count_after = check_existing_models()
        
        if has_models_after:
            elapsed = time.time() - start_time
            logger.info(f"✓ PaddleOCR models successfully verified")
            logger.info(f"Total model files: {file_count_after}")
            logger.info(f"Time taken: {elapsed:.1f} seconds")
            
            # Create a marker file to indicate successful pre-download
            marker_file = model_dir_after / '.preload_complete'
            marker_file.touch()
            logger.info(f"Created marker file: {marker_file}")
        else:
            logger.warning("Models may not have been downloaded successfully")
            logger.info("They will be downloaded on first run")
        
        return True
        
    except Exception as e:
        logger.error(f"PaddleOCR initialization failed: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        
        # Even if initialization fails, don't fail the build
        logger.info("Models will be downloaded on first run instead")
        return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
