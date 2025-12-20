import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from paddleocr import PaddleOCR

def test_ocr_direct():
    print("Testing PaddleOCR directly with aggressive settings...")
    
    # Initialize PaddleOCR with aggressive settings
    ocr = PaddleOCR(
        use_angle_cls=True,
        lang='ru',
        use_gpu=False,
        show_log=False,
        det_db_thresh=0.1,
        det_db_box_thresh=0.1,
        det_db_unclip_ratio=2.5,
        det_db_score_mode="slow",
        rec_thresh=0.01,
        enable_mkldnn=True
    )
    
    print("OCR initialized")
    
    # Load test image
    img_path = "test_img/frame_000001.png"
    frame = cv2.imread(img_path)
    if frame is None:
        print("Failed to load image")
        return False
    
    print(f"Image shape: {frame.shape}")
    
    # Apply enhancement (CLAHE) similar to mask_service
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8,8))
    enhanced_gray = clahe.apply(gray)
    enhanced = cv2.cvtColor(enhanced_gray, cv2.COLOR_GRAY2BGR)
    
    print("Running OCR...")
    result = ocr.ocr(enhanced, cls=True, rec=True)
    print(f"Result type: {type(result)}")
    
    if result is None:
        print("OCR returned None")
        return False
    
    if not result:
        print("OCR returned empty list")
        return False
    
    if not result[0]:
        print("No detections in first element")
        return False
    
    detections = result[0]
    print(f"Number of detections: {len(detections)}")
    
    for i, det in enumerate(detections[:3]):  # Show first 3
        coords = det[0]
        text_info = det[1]
        print(f"Detection {i}: coords {coords}, text: {text_info[0]}, confidence: {text_info[1]}")
    
    # Create mask
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for det in detections:
        coords = det[0]
        points = np.array(coords, dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    
    white_pixels = np.sum(mask > 0)
    total_pixels = h * w
    print(f"White pixels in mask: {white_pixels} ({(white_pixels/total_pixels)*100:.2f}%)")
    
    if white_pixels > 0:
        print("SUCCESS: OCR detected text")
        # Save mask
        cv2.imwrite("test_direct_mask.png", mask)
        print("Mask saved to test_direct_mask.png")
        return True
    else:
        print("FAILURE: No text detected")
        return False

if __name__ == "__main__":
    # Set environment variable to disable model source check
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    success = test_ocr_direct()
    sys.exit(0 if success else 1)
