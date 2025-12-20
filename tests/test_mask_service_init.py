import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.basicConfig(level=logging.INFO)

from src.services.mask_service import MaskGeneratorService

def test_init():
    print("Testing MaskGeneratorService initialization...")
    
    try:
        service = MaskGeneratorService(lang='ru', mask_dilation=15, use_gpu_for_ocr=False, confidence_threshold=0.1)
        print(f"Service created. OCR available: {service.ocr is not None}")
        
        if service.ocr is None:
            print("ERROR: OCR is None, initialization failed.")
            return False
        
        print("SUCCESS: OCR initialized.")
        return True
        
    except Exception as e:
        print(f"ERROR during initialization: {e}")
        return False

if __name__ == "__main__":
    # Set environment variable to disable model source check
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    success = test_init()
    sys.exit(0 if success else 1)
