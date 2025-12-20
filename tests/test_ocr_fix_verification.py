import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from pathlib import Path
from src.services.mask_service import MaskGeneratorService

def test_enhancement():
    print("Testing MaskGeneratorService with enhancement...")
    
    # Initialize service with aggressive settings
    service = MaskGeneratorService(lang='ru', mask_dilation=15, use_gpu_for_ocr=False, confidence_threshold=0.1)
    
    # Load test image
    img_path = Path("test_img/frame_000001.png")
    if not img_path.exists():
        print(f"Test image not found: {img_path}")
        return False
    
    frame = cv2.imread(str(img_path))
    if frame is None:
        print("Failed to load image")
        return False
    
    print(f"Image shape: {frame.shape}")
    
    # Test enhancement method
    enhanced = service._enhance_image_for_ocr(frame)
    print(f"Enhanced image shape: {enhanced.shape}")
    
    # Generate mask for single frame
    masks = service._process_batch_with_hybrid_detection([frame])
    if not masks:
        print("No masks generated")
        return False
    
    mask = masks[0]
    white_pixels = np.sum(mask > 0)
    total_pixels = mask.shape[0] * mask.shape[1]
    print(f"Mask shape: {mask.shape}")
    print(f"White pixels: {white_pixels} ({(white_pixels/total_pixels)*100:.2f}%)")
    
    # Save mask for visual inspection
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    mask_path = output_dir / "test_mask.png"
    cv2.imwrite(str(mask_path), mask)
    print(f"Mask saved to {mask_path}")
    
    # Check if we have any white pixels
    if white_pixels > 0:
        print("SUCCESS: Mask contains text detections (white pixels > 0)")
        return True
    else:
        print("FAILURE: Mask is empty (no text detected)")
        return False

if __name__ == "__main__":
    success = test_enhancement()
    sys.exit(0 if success else 1)
