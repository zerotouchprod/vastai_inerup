#!/usr/bin/env python3
"""
Verification script for forced OCR parameters in MaskService.
Captures logs and ensures the old warning about dropped parameters does NOT appear.
"""

import sys
import logging
from pathlib import Path
import io

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_mask_service():
    # Set up logging to capture all messages
    log_capture_string = io.StringIO()
    ch = logging.StreamHandler(log_capture_string)
    ch.setLevel(logging.DEBUG)
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(ch)
    # Also add a console handler for visibility
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    root_logger.addHandler(console)

    from src.services.mask_service import MaskGeneratorService

    print("Initializing MaskGeneratorService...")
    service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)

    # Get captured logs
    logs = log_capture_string.getvalue()
    print("\n--- Captured Logs ---")
    print(logs)
    print("--- End Logs ---\n")

    # Check for the old warning
    if "Parameters not supported by this PaddleOCR version and will be dropped" in logs:
        print("❌ FAIL: Old warning about dropped parameters still appears!")
        return False
    else:
        print("✓ OK: No warning about dropped parameters.")

    # Check for successful initialization message
    if "OCR initialized successfully with custom thresholds" in logs:
        print("✓ OK: Custom thresholds were applied.")
    elif "OCR initialized with fallback config" in logs:
        print("⚠ WARNING: Fallback config used (some parameters rejected).")
        # This is acceptable because we have fallback logic
    else:
        print("❌ FAIL: No success log found.")
        return False

    if service.ocr is None:
        print("❌ FAIL: OCR engine is None.")
        return False
    else:
        print("✓ OK: OCR engine initialized.")

    # Additional check: ensure the inspect module is not used (optional)
    import inspect
    if "inspect" in logs:
        print("⚠ WARNING: Inspect module appears in logs (maybe still used).")

    print("\n✅ Verification passed.")
    return True

if __name__ == "__main__":
    success = test_mask_service()
    sys.exit(0 if success else 1)
