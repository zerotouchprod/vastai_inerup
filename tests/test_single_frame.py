#!/usr/bin/env python3
"""
Test subtitle removal on a single frame with different profiles.
Fast comparison without processing all frames.
"""

import os
import sys
import cv2
import numpy as np
from pathlib import Path
import tempfile
import shutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.inpainting.lama_adapter import LaMaAdapter

def test_single_frame(profile_name, env_file, video_path, output_root, roi_str, frame_num=0):
    """Test subtitle removal on a single frame."""
    print(f"\n=== Testing profile: {profile_name} ===")
    
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
    
    # Create output directory
    output_dir = output_root / profile_name
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract single frame
    cap = cv2.VideoCapture(str(video_path))
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print("Failed to extract frame")
        return False
    
    # Save original frame
    original_path = output_dir / "original.png"
    cv2.imwrite(str(original_path), frame)
    
    h, w = frame.shape[:2]
    
    # Apply ROI if specified
    if roi_str:
        parts = roi_str.split(',')
        if len(parts) == 4:
            x = int(w * float(parts[0]))
            y = int(h * float(parts[1]))
            roi_w = int(w * float(parts[2]))
            roi_h = int(h * float(parts[3]))
            roi_frame = frame[y:y+roi_h, x:x+roi_w]
        else:
            roi_frame = frame
    else:
        roi_frame = frame
    
    # Initialize OCR with parameters from env
    try:
        ocr_params = {
            'text_threshold': float(env_vars.get('OCR_TEXT_THRESHOLD', 0.1)),
            'low_text': float(env_vars.get('OCR_LOW_TEXT', 0.1)),
            'link_threshold': float(env_vars.get('OCR_LINK_THRESHOLD', 0.25)),
            'canvas_size': int(env_vars.get('OCR_CANVAS_SIZE', 2240)),
            'mag_ratio': float(env_vars.get('OCR_MAG_RATIO', 1.3)),
        }
        ocr = PaddleWrapper(lang='ru', use_gpu=False, detector_params=ocr_params)
    except Exception as e:
        print(f"Failed to initialize OCR: {e}")
        return False
    
    # Detect text
    confidence_threshold = float(env_vars.get('CONFIDENCE_THRESHOLD', 0.15))
    detections = ocr.detect(roi_frame, confidence_threshold=confidence_threshold)
    
    print(f"Detected {len(detections)} text blocks")
    
    # Create mask
    mask = np.zeros(roi_frame.shape[:2], dtype=np.uint8)
    for det in detections:
        points = np.array(det['points'], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)
    
    # Apply dilation
    dilation = int(env_vars.get('MASK_DILATION', 10))
    if dilation > 0:
        kernel = np.ones((dilation, dilation), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=1)
    
    # If ROI was applied, place mask back into full frame
    if roi_str and len(parts) == 4:
        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_mask[y:y+roi_h, x:x+roi_w] = mask
        mask = full_mask
    
    # Save mask
    mask_path = output_dir / "mask.png"
    cv2.imwrite(str(mask_path), mask)
    
    # Draw bounding boxes on frame for visualization
    vis_frame = frame.copy()
    if roi_str and len(parts) == 4:
        roi_vis = vis_frame[y:y+roi_h, x:x+roi_w].copy()
        for det in detections:
            points = np.array(det['points'], dtype=np.int32)
            cv2.polylines(roi_vis, [points], True, (0, 255, 0), 2)
            text = f"{det['text']} ({det['confidence']:.2f})"
            cv2.putText(roi_vis, text, (points[0][0], points[0][1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        vis_frame[y:y+roi_h, x:x+roi_w] = roi_vis
    
    detection_path = output_dir / "detection.png"
    cv2.imwrite(str(detection_path), vis_frame)
    
    # Run inpainting on single frame
    try:
        lama = LaMaAdapter()
        
        # Create temporary directories
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            frames_dir = tmp_path / "frames"
            masks_dir = tmp_path / "masks"
            result_dir = tmp_path / "result"
            
            frames_dir.mkdir()
            masks_dir.mkdir()
            result_dir.mkdir()
            
            # Save frame and mask
            cv2.imwrite(str(frames_dir / "frame_0000.png"), frame)
            cv2.imwrite(str(masks_dir / "frame_0000.png"), mask)
            
            # Run inpainting
            lama.process(frames_dir, masks_dir, result_dir)
            
            # Load result
            result_path = result_dir / "frame_0000.png"
            if result_path.exists():
                result = cv2.imread(str(result_path))
                result_path_out = output_dir / "inpainted.png"
                cv2.imwrite(str(result_path_out), result)
                print(f"✅ Inpainting completed")
                
                # Create comparison image
                comparison = np.hstack([
                    frame,
                    cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR),
                    result
                ])
                comparison_path = output_dir / "comparison.png"
                cv2.imwrite(str(comparison_path), comparison)
                
                return True
            else:
                print("❌ No output from LaMa")
                return False
                
    except Exception as e:
        print(f"❌ Inpainting failed: {e}")
        return False

def main():
    """Test all profiles on a single frame."""
    video_path = Path("video/1smaho.mp4")
    if not video_path.exists():
        print(f"Video not found: {video_path}")
        return
    
    roi_str = "0.05,0.5,0.9,0.3"
    output_root = Path("../output/single_frame_tests")
    output_root.mkdir(parents=True, exist_ok=True)
    
    profiles = [
        ('current_default', '.env'),
        ('precision', '.env.precision'),
        ('balanced', '.env.balanced'),
        ('glow', '.env.glow'),
        ('purple_glow', '.env.purple_glow'),
        ('ultra_sensitive', '.env.ultra_sensitive'),
    ]
    
    # Ensure all env files exist
    for profile_name, env_file in profiles:
        if not Path(env_file).exists():
            print(f"Warning: {env_file} not found")
    
    results = {}
    
    for profile_name, env_file in profiles:
        if Path(env_file).exists():
            success = test_single_frame(profile_name, env_file, video_path, output_root, roi_str)
            results[profile_name] = success
        else:
            results[profile_name] = False
    
    # Print summary
    print("\n" + "="*80)
    print("SINGLE FRAME TEST SUMMARY")
    print("="*80)
    
    for profile_name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{profile_name:<20} {status}")
    
    print(f"\nResults saved to: {output_root}")
    print("Each profile folder contains:")
    print("  - original.png: original frame")
    print("  - mask.png: generated mask")
    print("  - detection.png: frame with bounding boxes")
    print("  - inpainted.png: inpainted result")
    print("  - comparison.png: side-by-side comparison")
    
    # Create HTML report
    html_path = output_root / "report.html"
    with open(html_path, 'w') as f:
        f.write("""
<!DOCTYPE html>
<html>
<head>
    <title>OCR Profiles Comparison</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        .profile { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
        .profile h2 { margin-top: 0; color: #555; }
        .images { display: flex; flex-wrap: wrap; gap: 10px; }
        .image { flex: 1; min-width: 300px; }
        .image img { max-width: 100%; height: auto; border: 1px solid #ccc; }
        .caption { font-size: 12px; color: #666; margin-top: 5px; }
        .success { background-color: #e8f5e8; }
        .failed { background-color: #f5e8e8; }
    </style>
</head>
<body>
    <h1>OCR Profiles Comparison for Subtitle Removal</h1>
    <p>Video: 1smaho.mp4 | ROI: 0.05,0.5,0.9,0.3 | Frame: 0</p>
""")
        
        for profile_name, success in results.items():
            status_class = "success" if success else "failed"
            status_text = "✅ SUCCESS" if success else "❌ FAILED"
            
            f.write(f"""
    <div class="profile {status_class}">
        <h2>{profile_name} - {status_text}</h2>
        <div class="images">
            <div class="image">
                <img src="{profile_name}/original.png" alt="Original">
                <div class="caption">Original Frame</div>
            </div>
            <div class="image">
                <img src="{profile_name}/detection.png" alt="Detection">
                <div class="caption">OCR Detection (green boxes)</div>
            </div>
            <div class="image">
                <img src="{profile_name}/mask.png" alt="Mask">
                <div class="caption">Generated Mask</div>
            </div>
            <div class="image">
                <img src="{profile_name}/inpainted.png" alt="Inpainted">
                <div class="caption">Inpainted Result</div>
            </div>
            <div class="image">
                <img src="{profile_name}/comparison.png" alt="Comparison">
                <div class="caption">Comparison (Original | Mask | Result)</div>
            </div>
        </div>
    </div>
""")
        
        f.write("""
</body>
</html>
""")
    
    print(f"\nHTML report: {html_path}")

if __name__ == '__main__':
    main()
