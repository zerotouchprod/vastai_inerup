"""
Test OCR fix for PaddleOCR compatibility.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_ocr_initialization():
    """Test that OCR can be initialized without errors."""
    logger.info("Testing OCR initialization...")
    
    try:
        # Add current directory to path
        sys.path.insert(0, '.')
        
        # Test OCR initialization
        from src.infrastructure.ocr.paddle_wrapper import ThreadSafeOCR
        
        # Try to initialize with GPU disabled (should work)
        logger.info("Initializing ThreadSafeOCR with use_gpu_for_ocr=False...")
        ocr = ThreadSafeOCR(lang='en', use_gpu_for_ocr=False)
        logger.info("✓ ThreadSafeOCR initialized successfully with GPU disabled")
        
        # Try to initialize with GPU enabled (might fail, but shouldn't crash)
        try:
            logger.info("Initializing ThreadSafeOCR with use_gpu_for_ocr=True...")
            ocr_gpu = ThreadSafeOCR(lang='en', use_gpu_for_ocr=True)
            logger.info("✓ ThreadSafeOCR initialized successfully with GPU enabled")
        except Exception as e:
            logger.info(f"⚠ ThreadSafeOCR with GPU enabled failed (expected if CUDA not available): {e}")
        
        # Test MaskGeneratorService
        from src.services.mask_service import MaskGeneratorService
        
        logger.info("Initializing MaskGeneratorService...")
        mask_service = MaskGeneratorService(lang='en')
        logger.info("✓ MaskGeneratorService initialized successfully")
        
        logger.info("\n" + "="*60)
        logger.info("SUCCESS: OCR initialization works correctly!")
        logger.info("The 'use_gpu' parameter issue has been resolved.")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ OCR initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_ocr_initialization()
    sys.exit(0 if success else 1)
