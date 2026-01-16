#!/usr/bin/env python3
"""
Manual test script to verify CUDA extension rebuild functionality.

This script tests the complete flow:
1. Check if spatial-correlation-sampler works
2. If broken, attempt rebuild
3. Verify RAFT can initialize

Run this before processing videos to validate setup.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def main():
    print("=" * 80)
    print("ProPainter RAFT CUDA Extension Test")
    print("=" * 80)
    print()
    
    # Step 1: Check spatial-correlation-sampler
    print("Step 1: Checking spatial-correlation-sampler...")
    from src.infrastructure.inpainting.raft_wrapper import check_spatial_correlation_sampler
    
    is_working, error = check_spatial_correlation_sampler()
    
    if is_working:
        print("✅ spatial-correlation-sampler is working")
    else:
        print(f"❌ spatial-correlation-sampler is broken: {error}")
        print()
        
        # Ask if user wants to attempt rebuild
        auto_rebuild = os.getenv("AUTO_REBUILD_CUDA_EXTENSIONS", "false").lower() == "true"
        
        if auto_rebuild:
            print("AUTO_REBUILD_CUDA_EXTENSIONS=true, attempting rebuild...")
        else:
            response = input("Attempt automatic rebuild? (y/n): ").strip().lower()
            if response != 'y':
                print("Skipping rebuild. Run with AUTO_REBUILD_CUDA_EXTENSIONS=true to auto-rebuild.")
                return 1
        
        print()
        print("Step 2: Attempting rebuild...")
        print("This will:")
        print("  1. Rebuild spatial-correlation-sampler package")
        print("  2. Rebuild ProPainter RAFT correlation extension")
        print("  3. Verify everything works")
        print()
        print("This may take up to 3 minutes...")
        print()
        
        from src.infrastructure.inpainting.raft_wrapper import rebuild_spatial_correlation_sampler
        
        success = rebuild_spatial_correlation_sampler()
        
        if not success:
            print()
            print("❌ Rebuild failed!")
            print()
            print("Manual fix required:")
            print("  1. Rebuild Docker image with correct CUDA version")
            print("  2. Or manually run:")
            print("     cd /opt/ProPainter/RAFT/core/correlation")
            print("     rm -rf build dist *.egg-info *.so")
            print("     python3 setup.py install")
            return 1
        
        print()
        print("✅ Rebuild completed successfully")
    
    print()
    print("Step 3: Testing ProPainter RAFT initialization...")
    
    try:
        from src.infrastructure.inpainting.raft_wrapper import validate_raft_availability
        validate_raft_availability()
        print("✅ ProPainter RAFT initialized successfully")
    except Exception as e:
        print(f"❌ ProPainter RAFT initialization failed: {e}")
        print()
        print("This usually means:")
        print("  - Python process needs restart (import cache)")
        print("  - Or Docker image needs rebuild")
        return 1
    
    print()
    print("=" * 80)
    print("✅ ALL TESTS PASSED")
    print("=" * 80)
    print()
    print("ProPainter is ready to use!")
    print("You can now run: python pipeline_v2.py --input video.mp4")
    print()
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

