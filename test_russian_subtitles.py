#!/usr/bin/env python3
"""Test subtitle removal on Russian subtitle images."""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_russian_subtitles():
    """Test subtitle removal on Russian subtitle images."""
    print("Testing subtitle removal on Russian subtitle images...")
    print("=" * 60)
    
    # Check if test_img directory exists
    test_img_dir = Path("test_img")
    if not test_img_dir.exists():
        print(f"ERROR: Directory '{test_img_dir}' not found!")
        print("Please create a 'test_img' directory with Russian subtitle images.")
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
    output_dir = Path("test_img_output")
    output_dir.mkdir(exist_ok=True)
    print(f"\nOutput will be saved to: {output_dir}")
    
    try:
        from infrastructure.processors.subtitle.native import SubtitleRemoverNative
        
        print("\nInitializing subtitle remover for Russian language...")
        remover = SubtitleRemoverNative(lang='ru')
        print("Subtitle remover initialized successfully!")
        
        print("\nProcessing images...")
        print("-" * 40)
        
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
                        print(f"    Subtitles were likely removed or modified")
                    else:
                        print(f"  [WARNING] Image was NOT modified (difference: 0)")
                        print(f"    Possible reasons:")
                        print(f"    1. No text detected (confidence threshold too high)")
                        print(f"    2. Text not recognized as Russian")
                        print(f"    3. Text too small or low quality")
                else:
                    print(f"  [WARNING] Could not read images for comparison")
            else:
                print(f"  [ERROR] Output file not created!")
        
        print("\n" + "=" * 60)
        print("Processing complete!")
        print(f"Check results in: {output_dir}")
        print("\nTo compare original vs processed:")
        print("  Original: test_img/")
        print("  Processed: test_img_output/")
        
        return True
        
    except ImportError as e:
        print(f"ERROR: Could not import subtitle remover: {e}")
        print("\nMake sure dependencies are installed:")
        print("  pip install paddleocr opencv-python-headless")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Set environment variable to skip model source check
    os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    
    success = test_russian_subtitles()
    
    if success:
        print("\n[SUCCESS] Test completed successfully!")
        sys.exit(0)
    else:
        print("\n[FAILED] Test failed!")
        sys.exit(1)
