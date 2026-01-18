#!/usr/bin/env python3
"""
Direct OCR testing with different parameter sets.
"""

import cv2
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper

def test_parameters(params_name, detector_params, mask_dilation=15, confidence_threshold=0.1):
    """Test OCR with specific detector parameters."""
    print(f"\n=== Testing: {params_name} ===")
    print(f"Parameters: {detector_params}")
    print(f"Mask dilation: {mask_dilation}")
    print(f"Confidence threshold: {confidence_threshold}")
    
    # Load test frame
    frame_path = Path("tests/video/1smaho.mp4")
    cap = cv2.VideoCapture(str(frame_path))
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print("Failed to read frame")
        return None
    
    # Apply ROI (0.05,0.5,0.9,0.3)
    h, w = frame.shape[:2]
    x = int(w * 0.05)
    y = int(h * 0.5)
    roi_w = int(w * 0.9)
    roi_h = int(h * 0.3)
    roi_frame = frame[y:y+roi_h, x:x+roi_w]
    
    # Initialize OCR with custom parameters
    ocr = PaddleWrapper(lang='ru', use_gpu=False, detector_params=detector_params)
    
    # Detect text
    detections = ocr.detect(roi_frame, confidence_threshold=confidence_threshold)
    
    print(f"Detected {len(detections)} text blocks")
    
    # Create mask
    mask = np.zeros(roi_frame.shape[:2], dtype=np.uint8)
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    
    # Apply dilation
    if mask_dilation > 0:
        kernel = np.ones((mask_dilation, mask_dilation), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
    
    # Calculate coverage
    total_pixels = roi_w * roi_h
    mask_pixels = np.sum(mask > 0)
    coverage = mask_pixels / total_pixels * 100
    
    print(f"Mask coverage: {coverage:.2f}% ({mask_pixels}/{total_pixels} pixels)")
    
    # Save visualization
    output_dir = Path("output/ocr_direct")
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
    cv2.imwrite(str(output_dir / f"{params_name}_frame.jpg"), vis_frame)
    cv2.imwrite(str(output_dir / f"{params_name}_mask.jpg"), mask)
    
    # Side-by-side comparison
    comparison = np.hstack([roi_frame, cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR), vis_frame])
    cv2.imwrite(str(output_dir / f"{params_name}_comparison.jpg"), comparison)
    
    return {
        'name': params_name,
        'detections': len(detections),
        'coverage': coverage,
        'mask_pixels': mask_pixels,
        'total_pixels': total_pixels,
        'texts': [det['text'] for det in detections],
        'confidences': [det['confidence'] for det in detections]
    }

def main():
    """Test multiple parameter sets."""
    
    # Parameter sets based on our profiles
    parameter_sets = [
        {
            'name': 'precision',
            'detector_params': {
                'text_threshold': 0.2,
                'low_text': 0.2,
                'link_threshold': 0.3,
                'canvas_size': 1920,
                'mag_ratio': 1.2,
                'threshold': 0.15,
                'bbox_min_score': 0.25,
                'bbox_min_size': 5,
            },
            'mask_dilation': 8,
            'confidence_threshold': 0.2
        },
        {
            'name': 'balanced',
            'detector_params': {
                'text_threshold': 0.1,
                'low_text': 0.1,
                'link_threshold': 0.25,
                'canvas_size': 2240,
                'mag_ratio': 1.3,
                'threshold': 0.1,
                'bbox_min_score': 0.2,
                'bbox_min_size': 3,
            },
            'mask_dilation': 10,
            'confidence_threshold': 0.15
        },
        {
            'name': 'glow',
            'detector_params': {
                'text_threshold': 0.3,
                'low_text': 0.3,
                'link_threshold': 0.4,
                'canvas_size': 1280,
                'mag_ratio': 1.0,
                'threshold': 0.2,
                'bbox_min_score': 0.3,
                'bbox_min_size': 8,
            },
            'mask_dilation': 5,
            'confidence_threshold': 0.3
        },
        {
            'name': 'current_default',
            'detector_params': {},  # Use defaults from PaddleWrapper
            'mask_dilation': 15,
            'confidence_threshold': 0.1
        },
        {
            'name': 'ultra_sensitive',
            'detector_params': {
                'text_threshold': 0.05,
                'low_text': 0.05,
                'link_threshold': 0.2,
                'canvas_size': 2560,
                'mag_ratio': 1.5,
                'threshold': 0.1,
                'bbox_min_score': 0.2,
                'bbox_min_size': 3,
            },
            'mask_dilation': 15,
            'confidence_threshold': 0.1
        }
    ]
    
    results = []
    
    for params in parameter_sets:
        result = test_parameters(
            params['name'],
            params['detector_params'],
            params['mask_dilation'],
            params['confidence_threshold']
        )
        if result:
            results.append(result)
    
    # Print summary
    print("\n" + "="*80)
    print("DIRECT OCR PARAMETERS TEST SUMMARY")
    print("="*80)
    
    for result in results:
        print(f"\n{result['name'].upper():<20}")
        print(f"  Detections: {result['detections']}")
        print(f"  Coverage: {result['coverage']:.2f}%")
        print(f"  Texts: {', '.join(result['texts'][:3])}")
        if len(result['texts']) > 3:
            print(f"    ... and {len(result['texts']) - 3} more")
        if result['confidences']:
            avg_conf = sum(result['confidences']) / len(result['confidences'])
            print(f"  Avg confidence: {avg_conf:.3f}")
    
    # Save detailed summary
    summary_path = Path("output/ocr_direct/summary.txt")
    with open(summary_path, 'w') as f:
        f.write("Direct OCR Parameters Test Summary\n")
        f.write("="*60 + "\n")
        for result in results:
            f.write(f"\nProfile: {result['name']}\n")
            f.write(f"  Detections: {result['detections']}\n")
            f.write(f"  Coverage: {result['coverage']:.2f}%\n")
            f.write(f"  Mask pixels: {result['mask_pixels']}/{result['total_pixels']}\n")
            f.write(f"  Texts: {', '.join(result['texts'])}\n")
            f.write(f"  Confidences: {[f'{c:.3f}' for c in result['confidences']]}\n")
            if result['confidences']:
                avg = sum(result['confidences']) / len(result['confidences'])
                f.write(f"  Average confidence: {avg:.3f}\n")
    
    print(f"\nDetailed summary saved to: {summary_path}")
    print("Visualizations saved to: output/ocr_direct/")
    
    # Recommendation
    print("\n" + "="*80)
    print("RECOMMENDATION")
    print("="*80)
    
    # Find best balance (not too high coverage, not too low detections)
    best = None
    for result in results:
        if result['detections'] > 0:
            if best is None or (0.1 < result['coverage'] < 20.0):
                best = result
    
    if best:
        print(f"\nRecommended profile: {best['name']}")
        print(f"  Coverage: {best['coverage']:.2f}% (reasonable)")
        print(f"  Detections: {best['detections']} text blocks")
        print(f"  Detected texts: {', '.join(best['texts'])}")
    else:
        print("\nNo suitable profile found. All have extreme coverage.")

if __name__ == '__main__':
    main()
