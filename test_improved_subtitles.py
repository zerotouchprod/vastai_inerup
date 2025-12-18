#!/usr/bin/env python3
"""Test improved subtitle removal on Russian subtitle images."""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_improved_subtitles():
    """Test improved subtitle removal on Russian subtitle images."""
    print("Testing IMPROVED subtitle removal on Russian subtitle images...")
    print("=" * 70)
    print("Parameters: mask_dilation=8, confidence_threshold=0.3")
    print("=" * 70)
    
    # Check if test_img directory exists
    test_img_dir = Path("test_img")
    if not test_img_dir.exists():
        print(f"ERROR: Directory '{test_img_dir}' not found!")
        return False
    
    # List images
    images = sorted(list(test_img_dir.glob("*.png")) + list(test_img_dir.glob("*.jpg")))
    if not images:
        print(f"ERROR: No images found in '{test_img_dir}'!")
        return False
    
    print(f"Found {len(images)} images:")
    for img in images:
        print(f"  - {img.name}")
    
    # Create output directory
    output_dir = Path("test_img_improved")
    output_dir.mkdir(exist_ok=True)
    print(f"\nOutput will be saved to: {output_dir}")
    
    try:
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative
        
        print("\nInitializing IMPROVED subtitle remover for Russian language...")
        print("Parameters: mask_dilation=8, confidence_threshold=0.3")
        remover = SubtitleRemoverNative(lang='ru', mask_dilation=8, confidence_threshold=0.3)
        print("Improved subtitle remover initialized successfully!")
        
        print("\nProcessing images with improved parameters...")
        print("-" * 50)
        
        # Process each image
        for i, img_path in enumerate(images):
            print(f"\n[{i+1}/{len(images)}] Processing: {img_path.name}")
            
            output_path = output_dir / img_path.name
            
            # Process single frame
            remover._process_single_frame(img_path, output_path)
            
            # Check if file was created
            if output_path.exists():
                print(f"  [OK] Saved to: {output_path.name}")
                
                # Check file size
                orig_size = img_path.stat().st_size
                new_size = output_path.stat().st_size
                print(f"  Original size: {orig_size:,} bytes")
                print(f"  Processed size: {new_size:,} bytes")
                print(f"  Size change: {((new_size - orig_size) / orig_size * 100):+.1f}%")
                
                # Load images to check if they're different
                import cv2
                import numpy as np
                
                orig_img = cv2.imread(str(img_path))
                proc_img = cv2.imread(str(output_path))
                
                if orig_img is not None and proc_img is not None:
                    diff = cv2.absdiff(orig_img, proc_img)
                    diff_sum = np.sum(diff)
                    
                    if diff_sum > 0:
                        print(f"  [OK] Image was modified (difference: {diff_sum:,})")
                        
                        # Calculate percentage of pixels changed
                        total_pixels = orig_img.shape[0] * orig_img.shape[1] * orig_img.shape[2]
                        change_percent = (diff_sum / (255 * total_pixels)) * 100
                        print(f"  Approx. {change_percent:.1f}% of pixels changed")
                        
                        # Check if we can see the difference visually
                        if change_percent > 1.0:
                            print(f"  [GOOD] Significant changes detected")
                        else:
                            print(f"  [WARNING] Minimal changes detected")
                    else:
                        print(f"  [WARNING] Image was NOT modified (difference: 0)")
                else:
                    print(f"  [WARNING] Could not read images for comparison")
            else:
                print(f"  [ERROR] Output file not created!")
        
        print("\n" + "=" * 70)
        print("IMPROVED processing complete!")
        print(f"Check results in: {output_dir}")
        print("\nTo compare:")
        print("  Original: test_img/")
        print("  Previous result: test_img_output/")
        print("  Improved result: test_img_improved/")
        
        return True
        
    except ImportError as e:
        print(f"ERROR: Could not import subtitle remover: {e}")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Set environment variable to skip model source check
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    
    success = test_improved_subtitles()
    
    if success:
        print("\n[SUCCESS] Improved test completed!")
        sys.exit(0)
    else:
        print("\n[FAILED] Improved test failed!")
        sys.exit(1)
