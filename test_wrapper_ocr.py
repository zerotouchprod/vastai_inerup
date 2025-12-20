import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from pathlib import Path
from src.infrastructure.ocr.paddle_wrapper import ThreadSafeOCR

def test_wrapper():
    print("Testing ThreadSafeOCR with aggressive settings...")
    
    # Initialize wrapper
    ocr = ThreadSafeOCR(lang='ru', use_gpu_for_ocr=False, use_angle_cls=True)
    
    print("OCR wrapper initialized")
    
    # Load test image
    img_path = Path("test_img/frame_000001.png")
    frame = cv2.imread(str(img_path))
    if frame is None:
        print("Failed to load image")
        return False
    
    print(f"Image shape: {frame.shape}")
    
    # Process batch (single image)
    masks = ocr.process_batch([frame], confidence_threshold=0.1)
    if not masks:
        print("No masks generated")
        return False
    
    mask = masks[0]
    white_pixels = np.sum(mask > 0)
    total_pixels = mask.shape[0] * mask.shape[1]
    print(f"Mask shape: {mask.shape}")
    print(f"White pixels: {white_pixels} ({(white_pixels/total_pixels)*100:.2f}%)")
    
    # Save mask
    output_dir = Path("test_output")
    output_dir.mkdir(exist_ok=True)
    mask_path = output_dir / "wrapper_mask.png"
    cv2.imwrite(str(mask_path), mask)
    print(f"Mask saved to {mask_path}")
    
    if white_pixels > 0:
        print("SUCCESS: Mask contains text detections")
        return True
    else:
        print("FAILURE: Mask is empty")
        return False

if __name__ == "__main__":
    # Set environment variable to disable model source check
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    success = test_wrapper()
    sys.exit(0 if success else 1)
