#!/usr/bin/env python3
"""
Test improved precision profile on problematic frame.
"""

import os
import sys
import cv2
import numpy as np
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper

def test_profile_on_frame(frame_path, profile_name, env_file):
    """Test OCR profile on specific frame."""
    print(f"\n=== Testing {profile_name} on {frame_path} ===")
    
    if not Path(frame_path).exists():
        print(f"Frame not found: {frame_path}")
        return
    
    # Load environment variables
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
                    env_vars[key.strip()] = value.strip()
    
    # Load frame
    frame = cv2.imread(frame_path)
    if frame is None:
        print("Failed to load frame")
        return
    
    h, w = frame.shape[:2]
    
    # Apply ROI (0.05,0.5,0.9,0.3)
    roi_str = "0.05,0.5,0.9,0.3"
    parts = roi_str.split(',')
    x = int(w * float(parts[0]))
    y = int(h * float(parts[1]))
    roi_w = int(w * float(parts[2]))
    roi_h = int(h * float(parts[3]))
    roi_frame = frame[y:y+roi_h, x:x+roi_w]
    
    # Initialize OCR
    ocr_params = {
        'text_threshold': float(env_vars.get('OCR_TEXT_THRESHOLD', 0.2)),
        'low_text': float(env_vars.get('OCR_LOW_TEXT', 0.2)),
        'link_threshold': float(env_vars.get('OCR_LINK_THRESHOLD', 0.3)),
        'canvas_size': int(env_vars.get('OCR_CANVAS_SIZE', 1920)),
        'mag_ratio': float(env_vars.get('OCR_MAG_RATIO', 1.2)),
    }
    
    print(f"Parameters: {ocr_params}")
    print(f"Confidence threshold: {env_vars.get('CONFIDENCE_THRESHOLD', 0.2)}")
    print(f"Mask dilation: {env_vars.get('MASK_DILATION', 8)}")
    
    ocr = PaddleWrapper(lang='ru', use_gpu=False, detector_params=ocr_params)
    
    # Detect text
    confidence_threshold = float(env_vars.get('CONFIDENCE_THRESHOLD', 0.2))
    detections = ocr.detect(roi_frame, confidence_threshold=confidence_threshold)
    
    print(f"\nDetections with threshold {confidence_threshold}: {len(detections)}")
    for i, det in enumerate(detections):
        text = det['text']
        confidence = det['confidence']
        points = det['points']
        bbox_area = cv2.contourArea(np.array(points, dtype=np.int32))
        print(f"  [{i}] '{text}' (conf: {confidence:.3f}, area: {bbox_area:.0f} px)")
    
    # Create mask
    mask = np.zeros(roi_frame.shape[:2], dtype=np.uint8)
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    
    # Apply dilation
    dilation = int(env_vars.get('MASK_DILATION', 8))
    if dilation > 0:
        kernel = np.ones((dilation, dilation), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
    
    # Calculate coverage
    total_pixels = roi_w * roi_h
    mask_pixels = np.sum(mask > 0)
    coverage = mask_pixels / total_pixels * 100
    
    print(f"\nMask coverage: {coverage:.2f}% ({mask_pixels}/{total_pixels} pixels)")
    
    # Save visualization
    output_dir = Path("../output/profile_comparison")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Draw bounding boxes
    vis_frame = roi_frame.copy()
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.polylines(vis_frame, [points], True, (0, 255, 0), 2)
        text = f"{det['text']} ({det['confidence']:.2f})"
        cv2.putText(vis_frame, text, (points[0][0], points[0][1] - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    # Save results
    cv2.imwrite(str(output_dir / f"{profile_name}_detection.png"), vis_frame)
    cv2.imwrite(str(output_dir / f"{profile_name}_mask.png"), mask)
    
    # Create comparison
    comparison = np.hstack([roi_frame, cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), vis_frame])
    cv2.imwrite(str(output_dir / f"{profile_name}_comparison.png"), comparison)
    
    print(f"Results saved to: {output_dir}/")
    
    return len(detections) > 0

def main():
    """Test all profiles on problematic frame."""
    frame_path = "../output/subtitle_removal_tests/precision/frame_0011.png"
    
    profiles = [
        ('precision', '.env.precision'),
        ('precision_improved', '.env.precision_improved'),
        ('purple_glow', '.env.purple_glow'),
        ('balanced', '.env.balanced'),
    ]
    
    results = {}
    
    for profile_name, env_file in profiles:
        if Path(env_file).exists():
            success = test_profile_on_frame(frame_path, profile_name, env_file)
            results[profile_name] = success
        else:
            print(f"Env file not found: {env_file}")
            results[profile_name] = False
    
    # Print summary
    print("\n" + "="*80)
    print("PROFILE COMPARISON ON PROBLEMATIC FRAME")
    print("="*80)
    
    for profile_name, success in results.items():
        status = "✅ DETECTED TEXT" if success else "❌ NO TEXT DETECTED"
        print(f"{profile_name:<25} {status}")
    
    print("\nRecommendation:")
    if results.get('precision_improved', False):
        print("✅ Use 'precision_improved' profile - detects text with reasonable thresholds")
    elif results.get('purple_glow', False):
        print("✅ Use 'purple_glow' profile - good balance for glowing subtitles")
    elif results.get('balanced', False):
        print("✅ Use 'balanced' profile - moderate sensitivity")
    else:
        print("❌ All profiles failed - need even lower thresholds")

if __name__ == '__main__':
    main()
