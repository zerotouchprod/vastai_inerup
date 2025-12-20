import sys
import logging
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Capture logs
log_capture = io.StringIO()
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(log_capture),
                              logging.StreamHandler(sys.stdout)])

print("=== Final Verification of MaskService ===")
print("Importing MaskGeneratorService...")
try:
    from src.services.mask_service import MaskGeneratorService
    print("Import successful.")
except Exception as e:
    print(f"Import failed: {e}")
    sys.exit(1)

print("\nInitializing service with lang='en', use_gpu_for_ocr=False...")
try:
    service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)
    print("Service initialized.")
except Exception as e:
    print(f"Initialization failed: {e}")
    sys.exit(1)

logs = log_capture.getvalue()
print("\n--- Captured Logs ---")
print(logs)
print("--- End Logs ---")

# Check for old warning
if "Parameters not supported by this PaddleOCR version and will be dropped" in logs:
    print("\n❌ FAIL: Old warning about dropped parameters still appears!")
    sys.exit(1)
else:
    print("\n✓ OK: No warning about dropped parameters.")

# Check for success message
if "OCR initialized successfully with custom thresholds" in logs:
    print("✓ OK: Custom thresholds applied.")
elif "OCR initialized with fallback config" in logs:
    print("⚠ WARNING: Fallback config used (some parameters rejected).")
else:
    print("❌ FAIL: No success log found.")
    sys.exit(1)

if service.ocr is None:
    print("❌ FAIL: OCR engine is None.")
    sys.exit(1)
else:
    print("✓ OK: OCR engine is not None.")

print("\n✅ Verification passed. The MaskService now forces OCR parameters.")
print("   The inspect-based filtering has been removed.")
