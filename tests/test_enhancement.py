import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from pathlib import Path
from src.services.mask_service import MaskGeneratorService

def test_enhancement():
    print("Testing image enhancement for OCR...")
    
    service = MaskGeneratorService()
    
    img_path = Path("test_img/frame_000001.png")
    frame = cv2.imread(str(img_path))
    if frame is None:
        print("Failed to load image")
        return False
    
    print(f"Original image shape: {frame.shape}")
    
    enhanced = service._enhance_image_for_ocr(frame)
    print(f"Enhanced image shape: {enhanced.shape}")
    
    # Convert enhanced to grayscale for comparison
    enhanced_gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    original_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Compute contrast metrics
    def contrast_metric(img):
        return np.std(img)
    
    orig_contrast = contrast_metric(original_gray)
    enh_contrast = contrast_metric(enhanced_gray)
    print(f"Original contrast (std): {orig_contrast:.2f}")
    print(f"Enhanced contrast (std): {enh_contrast:.2f}")
    print(f"Contrast improvement: {enh_contrast/orig_contrast:.2f}x")
    
    # Save images
    output_dir = Path("test_enhancement_output")
    output_dir.mkdir(exist_ok=True)
    
    cv2.imwrite(str(output_dir / "original.jpg"), frame)
    cv2.imwrite(str(output_dir / "enhanced.jpg"), enhanced)
    cv2.imwrite(str(output_dir / "original_gray.jpg"), original_gray)
    cv2.imwrite(str(output_dir / "enhanced_gray.jpg"), enhanced_gray)
    
    print(f"Images saved to {output_dir}")
    
    # Check if enhancement increased contrast
    if enh_contrast > orig_contrast:
        print("SUCCESS: Enhancement increased contrast")
        return True
    else:
        print("WARNING: Enhancement did not increase contrast")
        return False

if __name__ == "__main__":
    success = test_enhancement()
    sys.exit(0 if success else 1)
