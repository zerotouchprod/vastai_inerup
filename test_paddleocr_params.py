#!/usr/bin/env python3
"""
Test script to check which PaddleOCR parameters are supported.
Run this to debug parameter issues.
"""

import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_paddleocr_params():
    """Test different PaddleOCR parameter combinations."""
    try:
        from paddleocr import PaddleOCR
        logger.info("PaddleOCR imported successfully")
    except ImportError as e:
        logger.error(f"Failed to import PaddleOCR: {e}")
        return
    
    # Test different parameter combinations
    # Add DISABLE_MODEL_SOURCE_CHECK=True to avoid connectivity checks
    base_params = {'lang': 'en', 'use_angle_cls': False}
    
    test_cases = [
        {
            'name': 'Minimal parameters',
            'params': {**base_params, 'show_log': False}
        },
        {
            'name': 'Minimal with model check disabled',
            'params': {**base_params, 'show_log': False, 'disable_model_source_check': True}
        },
        {
            'name': 'With GPU (use_gpu)',
            'params': {**base_params, 'show_log': False, 'disable_model_source_check': True, 'use_gpu': True}
        },
        {
            'name': 'With GPU (gpu)',
            'params': {**base_params, 'show_log': False, 'disable_model_source_check': True, 'gpu': True}
        },
        {
            'name': 'With det parameters',
            'params': {
                **base_params,
                'show_log': False,
                'disable_model_source_check': True,
                'det_db_thresh': 0.3,
                'det_db_box_thresh': 0.5,
                'det_db_unclip_ratio': 1.6,
                'det_limit_side_len': 960
            }
        },
        {
            'name': 'With CPU optimization',
            'params': {
                **base_params,
                'show_log': False,
                'disable_model_source_check': True,
                'enable_mkldnn': True,
                'cpu_threads': 4
            }
        },
    ]
    
    for test_case in test_cases:
        logger.info(f"\n{'='*60}")
        logger.info(f"Testing: {test_case['name']}")
        logger.info(f"Parameters: {test_case['params']}")
        
        try:
            ocr = PaddleOCR(**test_case['params'])
            logger.info("✅ Success: PaddleOCR initialized")
            
            # Try to get version info if available
            try:
                import paddleocr
                logger.info(f"PaddleOCR version: {paddleocr.__version__}")
            except:
                pass
                
        except Exception as e:
            logger.error(f"❌ Failed: {type(e).__name__}: {e}")
            
            # Check if it's a parameter error
            if "Unknown argument" in str(e):
                # Parse which parameter is unknown
                import re
                match = re.search(r"Unknown argument: (\w+)", str(e))
                if match:
                    unknown_param = match.group(1)
                    logger.error(f"Unknown parameter: {unknown_param}")
                    
                    # Try without the unknown parameter
                    test_case['params'].pop(unknown_param, None)
                    logger.info(f"Trying again without {unknown_param}...")
                    try:
                        ocr = PaddleOCR(**test_case['params'])
                        logger.info("✅ Success after removing unknown parameter")
                    except Exception as e2:
                        logger.error(f"❌ Still failed: {e2}")

def check_paddleocr_version():
    """Check PaddleOCR version and available parameters."""
    try:
        import paddleocr
        logger.info(f"\n{'='*60}")
        logger.info(f"PaddleOCR package version: {paddleocr.__version__}")
        
        # Try to inspect the PaddleOCR class
        from paddleocr import PaddleOCR
        import inspect
        
        # Get constructor signature
        sig = inspect.signature(PaddleOCR.__init__)
        logger.info("\nPaddleOCR.__init__ parameters:")
        for param_name, param in sig.parameters.items():
            if param_name != 'self':
                logger.info(f"  - {param_name}: {param}")
                
    except Exception as e:
        logger.error(f"Failed to check version: {e}")

if __name__ == "__main__":
    logger.info("Testing PaddleOCR parameter compatibility")
    check_paddleocr_version()
    test_paddleocr_params()
    logger.info("\nTest completed")
