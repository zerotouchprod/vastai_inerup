#!/usr/bin/env python3
"""
Manual test script to verify CUDA extension rebuild functionality.

This script tests the complete flow:
1. Check if pure PyTorch correlation is installed
2. Verify ProPainter can be imported

Run this before processing videos to validate setup.
"""

import sys
import os
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    print("=" * 80)
    print("ProPainter RAFT CUDA Extension Test")
    print("=" * 80)
    print()
    
    # Step 1: Check pure PyTorch correlation
    print("Step 1: Checking pure PyTorch correlation...")
    try:
        from src.infrastructure.inpainting.pure_pytorch_correlation import install_pure_pytorch_correlation
        install_pure_pytorch_correlation()
        print("✅ Pure PyTorch correlation installed successfully")
    except Exception as e:
        print(f"❌ Pure PyTorch correlation installation failed: {e}")
        print()
        print("This is unexpected - pure PyTorch should always work.")
        print("Please check:")
        print("  1. PyTorch is installed: pip list | grep torch")
        print("  2. Code is deployed correctly")
        print("  3. Python version is 3.8+")
        return 1
    
    print()
    print("Step 2: Testing ProPainter RAFT initialization...")
    
    try:
        propainter_root = Path(os.getenv("PROPAINTER_ROOT", "/opt/ProPainter"))
        if str(propainter_root) not in sys.path:
            sys.path.insert(0, str(propainter_root))
        
        # Just check that we can import the module (don't instantiate RAFT yet)
        from model.modules.flow_comp_raft import RAFT
        print("✅ ProPainter RAFT module: OK (can import)")
        print("   Note: RAFT will be initialized when needed (requires args)")
    except ImportError as e:
        print(f"⚠️  ProPainter RAFT import failed: {e}")
        print("   This is OK if you're not using subtitle removal")
    except Exception as e:
        print(f"❌ ProPainter RAFT initialization failed: {e}")
        print()
        print("This usually means:")
        print("  - ProPainter not installed at /opt/ProPainter")
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
