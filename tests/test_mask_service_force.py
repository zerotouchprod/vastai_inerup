import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

from src.services.mask_service import MaskGeneratorService

print("Testing MaskGeneratorService with forced parameters...")
service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)
if service.ocr:
    print("SUCCESS: OCR initialized")
    print("Check logs above for 'Parameters not supported... dropped' - should NOT appear.")
else:
    print("FAIL: OCR is None")
    sys.exit(1)
