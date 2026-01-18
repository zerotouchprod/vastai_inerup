#!/usr/bin/env python3
"""
Analyze why OCR fails on specific frame.
"""

import os
import sys
import cv2
import numpy as np
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper

def analyze_frame(frame_path, profile_name, env_file):
    """Analyze OCR detection on specific frame."""
    print(f"\n=== Analyzing frame: {frame_path} with profile: {profile_name} ===")
    
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
    print(f"Frame size: {w}x{h}")
    
    # Apply ROI (0.05,0.5,0.9,0.3)
    roi_str = "0.05,0.5,0.9,0.3"
    parts = roi_str.split(',')
    x = int(w * float(parts[0]))
    y = int(h * float(parts[1]))
    roi_w = int(w * float(parts[2]))
    roi_h = int(h * float(parts[3]))
    roi_frame = frame[y:y+roi_h, x:x+roi_w]
    
    print(f"ROI: {x},{y},{roi_w},{roi_h}")
    
    # Initialize OCR with parameters from env
    ocr_params = {
        'text_threshold': float(env_vars.get('OCR_TEXT_THRESHOLD', 0.2)),
        'low_text': float(env_vars.get('OCR_LOW_TEXT', 0.2)),
        'link_threshold': float(env_vars.get('OCR_LINK_THRESHOLD', 0.3)),
        'canvas_size': int(env_vars.get('OCR_CANVAS_SIZE', 1920)),
        'mag_ratio': float(env_vars.get('OCR_MAG_RATIO', 1.2)),
    }
    
    print(f"OCR parameters: {ocr_params}")
    print(f"Confidence threshold: {env_vars.get('CONFIDENCE_THRESHOLD', 0.2)}")
    
    ocr = PaddleWrapper(lang='ru', use_gpu=False, detector_params=ocr_params)
    
    # Detect text with different confidence thresholds
    confidence_thresholds = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3]
    
    for conf_thresh in confidence_thresholds:
        detections = ocr.detect(roi_frame, confidence_threshold=conf_thresh)
        print(f"\nConfidence threshold {conf_thresh}: {len(detections)} detections")
        
        for i, det in enumerate(detections):
            text = det['text']
            confidence = det['confidence']
            points = det['points']
            bbox_area = cv2.contourArea(np.array(points, dtype=np.int32))
            print(f"  [{i}] '{text}' (conf: {confidence:.3f}, area: {bbox_area:.0f} px)")
    
    # Save ROI for visual inspection
    output_dir = Path("output/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    roi_path = output_dir / "roi_cropped.png"
    cv2.imwrite(str(roi_path), roi_frame)
    print(f"\nROI saved to: {roi_path}")
    
    # Create histogram of ROI to check contrast
    gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    
    # Find min, max, mean intensity
    mean_intensity = np.mean(gray)
    std_intensity = np.std(gray)
    min_intensity = np.min(gray)
    max_intensity = np.max(gray)
    
    print(f"\nROI intensity analysis:")
    print(f"  Mean: {mean_intensity:.1f}")
    print(f"  Std: {std_intensity:.1f}")
    print(f"  Min: {min_intensity}")
    print(f"  Max: {max_intensity}")
    print(f"  Contrast (max-min): {max_intensity - min_intensity}")
    
    # Check if text might be low contrast
    if std_intensity < 30:
        print("⚠️  Low contrast detected - text may be hard to detect")
    
    # Save histogram
    import matplotlib.pyplot as plt
    plt.figure(figsize=(10, 4))
    plt.subplot(1, 2, 1)
    plt.imshow(cv2.cvtColor(roi_frame, cv2.COLOR_BGR2RGB))
    plt.title('ROI')
    plt.axis('off')
    
    plt.subplot(1, 2, 2)
    plt.plot(hist)
    plt.title('Intensity Histogram')
    plt.xlabel('Pixel Intensity')
    plt.ylabel('Frequency')
    plt.tight_layout()
    plt.savefig(str(output_dir / "roi_analysis.png"), dpi=150)
    plt.close()
    
    print(f"Analysis saved to: {output_dir}/")

def main():
    """Analyze specific frame."""
    frame_path = "output/subtitle_removal_tests/precision/frame_0011.png"
    profile_name = "precision"
    env_file = ".env.precision"
    
    analyze_frame(frame_path, profile_name, env_file)
    
    # Also analyze with purple_glow profile for comparison
    print("\n" + "="*80)
    analyze_frame(frame_path, "purple_glow", ".env.purple_glow")

if __name__ == '__main__':
    main()
