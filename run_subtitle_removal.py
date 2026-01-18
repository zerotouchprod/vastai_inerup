#!/usr/bin/env python3
"""
Run subtitle removal with different OCR profiles.
Bypasses GPU requirement for testing.
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
from src.core.config import get_config

def extract_frames(video_path, output_dir, max_frames=25):
    """Extract frames from video."""
    cap = cv2.VideoCapture(str(video_path))
    frame_count = 0
    frames = []
    
    while frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break
        frame_path = output_dir / f"frame_{frame_count:04d}.png"
        cv2.imwrite(str(frame_path), frame)
        frames.append(frame_path)
        frame_count += 1
    
    cap.release()
    print(f"Extracted {len(frames)} frames")
    return frames

def create_masks(frames, ocr, roi_str, dilation):
    """Create masks using OCR."""
    masks_dir = Path(tempfile.mkdtemp())
    masks = []
    
    for i, frame_path in enumerate(frames):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue
        
        h, w = frame.shape[:2]
        # Apply ROI if specified
        if roi_str:
            # Parse ROI "0.05,0.5,0.9,0.3"
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
        
        # Detect text
        detections = ocr.detect(roi_frame, confidence_threshold=0.15)
        
        # Create mask
        mask = np.zeros(roi_frame.shape[:2], dtype=np.uint8)
        for det in detections:
            points = np.array(det['points'], dtype=np.int32)
            cv2.fillPoly(mask, [points], 255)
        
        # Apply dilation
        if dilation > 0:
            kernel = np.ones((dilation, dilation), np.uint8)
            mask = cv2.dilate(mask, kernel, iterations=1)
        
        # If ROI was applied, place mask back into full frame
        if roi_str and len(parts) == 4:
            full_mask = np.zeros((h, w), dtype=np.uint8)
            full_mask[y:y+roi_h, x:x+roi_w] = mask
            mask = full_mask
        
        # Save mask
        mask_path = masks_dir / f"frame_{i:04d}.png"
        cv2.imwrite(str(mask_path), mask)
        masks.append(mask_path)
    
    return masks_dir, masks

def run_profile(profile_name, env_file, video_path, output_root, roi_str):
    """Run subtitle removal with a specific profile."""
    print(f"\n=== Running profile: {profile_name} ===")
    
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
    
    # Extract frames
    frames_dir = Path(tempfile.mkdtemp())
    frames = extract_frames(video_path, frames_dir)
    
    if not frames:
        print("No frames extracted")
        return False
    
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
    
    # Create masks
    dilation = int(env_vars.get('MASK_DILATION', 10))
    masks_dir, masks = create_masks(frames, ocr, roi_str, dilation)
    
    # Initialize LaMa adapter
    try:
        lama = LaMaAdapter()
    except Exception as e:
        print(f"Failed to initialize LaMa: {e}")
        return False
    
    # Run inpainting
    try:
        result_dir = lama.process(frames_dir, masks_dir, output_dir)
        print(f"✅ Inpainting completed: {result_dir}")
        
        # Copy first few frames for visualization
        for i in range(min(5, len(frames))):
            src_frame = frames[i]
            src_mask = masks[i]
            dst_frame = output_dir / f"original_{i:02d}.png"
            dst_mask = output_dir / f"mask_{i:02d}.png"
            dst_result = output_dir / f"result_{i:02d}.png"
            
            shutil.copy(src_frame, dst_frame)
            shutil.copy(src_mask, dst_mask)
            
            # Find result frame
            result_frame = output_dir / f"frame_{i:04d}.png"
            if result_frame.exists():
                shutil.copy(result_frame, dst_result)
        
        return True
        
    except Exception as e:
        print(f"❌ Inpainting failed: {e}")
        return False
    
    finally:
        # Cleanup temp directories
        shutil.rmtree(frames_dir, ignore_errors=True)
        shutil.rmtree(masks_dir, ignore_errors=True)

def main():
    """Run all profiles."""
    video_path = Path("tests/video/1smaho.mp4")
    if not video_path.exists():
        print(f"Video not found: {video_path}")
        return
    
    roi_str = "0.05,0.5,0.9,0.3"
    output_root = Path("output/subtitle_removal_tests")
    output_root.mkdir(parents=True, exist_ok=True)
    
    profiles = [
        ('current_default', '.env'),
        ('precision', '.env.precision'),
        ('balanced', '.env.balanced'),
        ('glow', '.env.glow'),
        ('purple_glow', '.env.purple_glow'),
        ('ultra_sensitive', '.env.ultra_sensitive'),
    ]
    
    # Create .env.ultra_sensitive if not exists
    if not Path('.env.ultra_sensitive').exists():
        with open('.env.ultra_sensitive', 'w') as f:
            f.write("""# Ultra sensitive profile
OCR_TEXT_THRESHOLD=0.05
OCR_LOW_TEXT=0.05
OCR_LINK_THRESHOLD=0.2
OCR_MAG_RATIO=1.5
OCR_CANVAS_SIZE=2560
MASK_DILATION=15
CONFIDENCE_THRESHOLD=0.1
OCR_THRESHOLD=0.1
OCR_BBOX_MIN_SCORE=0.2
OCR_BBOX_MIN_SIZE=3
FORCE_CPU=True
USE_GPU_FOR_OCR=False
""")
    
    # Create default .env if not exists
    if not Path('.env').exists():
        with open('.env', 'w') as f:
            f.write("""# Default profile
FORCE_CPU=True
USE_GPU_FOR_OCR=False
""")
    
    results = {}
    
    for profile_name, env_file in profiles:
        if Path(env_file).exists():
            success = run_profile(profile_name, env_file, video_path, output_root, roi_str)
            results[profile_name] = success
        else:
            print(f"Env file not found: {env_file}")
            results[profile_name] = False
    
    # Print summary
    print("\n" + "="*80)
    print("SUBTITLE REMOVAL TEST SUMMARY")
    print("="*80)
    
    for profile_name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{profile_name:<20} {status}")
    
    print(f"\nResults saved to: {output_root}")
    print("Each profile folder contains:")
    print("  - original_XX.png: original frame")
    print("  - mask_XX.png: generated mask")
    print("  - result_XX.png: inpainted result")
    print("  - frame_XXXX.png: all inpainted frames")

if __name__ == '__main__':
    main()
