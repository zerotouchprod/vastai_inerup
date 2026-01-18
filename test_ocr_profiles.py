#!/usr/bin/env python3
"""
Test OCR detection with different profiles on a single frame.
"""

import cv2
import numpy as np
import os
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.core.config import get_config, AppConfig

def test_profile(profile_name, env_file):
    """Test OCR detection with a specific profile."""
    print(f"\n=== Testing profile: {profile_name} ===")
    
    # Load environment variables from file
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value
    
    # Reload config to pick up new env vars
    global _config
    from src.core.config import _config
    _config = None
    config = get_config()
    
    print(f"OCR_TEXT_THRESHOLD: {config.OCR_TEXT_THRESHOLD}")
    print(f"OCR_LOW_TEXT: {config.OCR_LOW_TEXT}")
    print(f"OCR_LINK_THRESHOLD: {config.OCR_LINK_THRESHOLD}")
    print(f"OCR_MAG_RATIO: {config.OCR_MAG_RATIO}")
    print(f"OCR_CANVAS_SIZE: {config.OCR_CANVAS_SIZE}")
    print(f"MASK_DILATION: {config.MASK_DILATION}")
    print(f"CONFIDENCE_THRESHOLD: {config.CONFIDENCE_THRESHOLD}")
    
    # Initialize OCR with Russian language
    try:
        ocr = PaddleWrapper(lang='ru', use_gpu=False)
    except Exception as e:
        print(f"Failed to initialize OCR: {e}")
        return None
    
    # Load test frame
    frame_path = Path("tests/video/1smaho.mp4")
    if not frame_path.exists():
        print(f"Test video not found: {frame_path}")
        return None
    
    # Extract first frame
    cap = cv2.VideoCapture(str(frame_path))
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print("Failed to read frame from video")
        return None
    
    # Apply ROI (0.05,0.5,0.9,0.3)
    h, w = frame.shape[:2]
    x = int(w * 0.05)
    y = int(h * 0.5)
    roi_w = int(w * 0.9)
    roi_h = int(h * 0.3)
    
    # Crop frame to ROI
    roi_frame = frame[y:y+roi_h, x:x+roi_w]
    
    # Detect text
    detections = ocr.detect(roi_frame, confidence_threshold=config.CONFIDENCE_THRESHOLD)
    
    print(f"Detected {len(detections)} text blocks")
    
    # Create mask
    mask = np.zeros(roi_frame.shape[:2], dtype=np.uint8)
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    
    # Apply dilation
    if config.MASK_DILATION > 0:
        kernel = np.ones((config.MASK_DILATION, config.MASK_DILATION), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
    
    # Calculate coverage
    total_pixels = roi_w * roi_h
    mask_pixels = np.sum(mask > 0)
    coverage = mask_pixels / total_pixels * 100
    
    print(f"Mask coverage: {coverage:.2f}% ({mask_pixels}/{total_pixels} pixels)")
    
    # Save visualization
    output_dir = Path("output/ocr_tests")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Draw bounding boxes on frame
    vis_frame = roi_frame.copy()
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.polylines(vis_frame, [points], True, (0, 255, 0), 2)
        cv2.putText(vis_frame, f"{det['text']} ({det['confidence']:.2f})", 
                   (points[0][0], points[0][1] - 5), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    
    # Save results
    cv2.imwrite(str(output_dir / f"{profile_name}_frame.jpg"), vis_frame)
    cv2.imwrite(str(output_dir / f"{profile_name}_mask.jpg"), mask)
    
    # Create side-by-side comparison
    comparison = np.hstack([roi_frame, cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), vis_frame])
    cv2.imwrite(str(output_dir / f"{profile_name}_comparison.jpg"), comparison)
    
    return {
        'profile': profile_name,
        'detections': len(detections),
        'coverage': coverage,
        'mask_pixels': mask_pixels,
        'total_pixels': total_pixels,
        'detection_texts': [det['text'] for det in detections],
        'detection_confidences': [det['confidence'] for det in detections]
    }

def main():
    """Test all profiles."""
    profiles = [
        ('precision', '.env.precision'),
        ('balanced', '.env.balanced'),
        ('glow', '.env.glow'),
    ]
    
    results = []
    
    for profile_name, env_file in profiles:
        if Path(env_file).exists():
            result = test_profile(profile_name, env_file)
            if result:
                results.append(result)
        else:
            print(f"Env file not found: {env_file}")
    
    # Print summary
    print("\n" + "="*80)
    print("OCR PROFILES SUMMARY")
    print("="*80)
    for result in results:
        print(f"\n{result['profile'].upper():<15}")
        print(f"  Detections: {result['detections']}")
        print(f"  Coverage: {result['coverage']:.2f}%")
        print(f"  Texts: {', '.join(result['detection_texts'][:5])}")
        if len(result['detection_texts']) > 5:
            print(f"    ... and {len(result['detection_texts']) - 5} more")
    
    # Save summary to file
    summary_path = Path("output/ocr_tests/summary.txt")
    with open(summary_path, 'w') as f:
        f.write("OCR Profiles Test Summary\n")
        f.write("="*50 + "\n")
        for result in results:
            f.write(f"\nProfile: {result['profile']}\n")
            f.write(f"  Detections: {result['detections']}\n")
            f.write(f"  Coverage: {result['coverage']:.2f}%\n")
            f.write(f"  Mask pixels: {result['mask_pixels']}/{result['total_pixels']}\n")
            f.write(f"  Texts: {', '.join(result['detection_texts'])}\n")
            f.write(f"  Confidences: {[f'{c:.2f}' for c in result['detection_confidences']]}\n")
    
    print(f"\nDetailed summary saved to: {summary_path}")
    print("Visualizations saved to: output/ocr_tests/")

if __name__ == '__main__':
    main()
