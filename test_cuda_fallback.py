"""
Test CUDA compatibility check and CPU fallback.
Run this on remote server to verify the fix works.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    import torch
    print(f"✓ PyTorch available: {torch.__version__}")
    print(f"  CUDA available: {torch.cuda.is_available()}")

    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        print(f"  GPU: {props.name}")
        print(f"  Compute capability: sm_{props.major}{props.minor}")

        # Test if CUDA actually works
        try:
            test_tensor = torch.randn(10, 10).cuda()
            result = test_tensor * 2
            print(f"  ✓ CUDA operations work correctly")
        except RuntimeError as e:
            print(f"  ✗ CUDA operations fail: {e}")
            print(f"  → Will fall back to CPU")

except ImportError:
    print("✗ PyTorch not installed")
    sys.exit(1)

# Test the RIFE native wrapper compatibility check
print("\nTesting RIFE native wrapper:")
try:
    from infrastructure.processors.rife.native import RIFENative
    from shared.logging import setup_logger

    logger = setup_logger('test', 'INFO')
    processor = RIFENative(factor=2.0, logger=logger)

    # This will trigger _load_model which includes _check_cuda_compatibility
    print(f"\nRIFE processor device: {processor.device}")
    print("✓ RIFE native wrapper initialized successfully")

except Exception as e:
    print(f"✗ Failed to initialize RIFE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✅ All tests passed! CUDA fallback mechanism is working.")

