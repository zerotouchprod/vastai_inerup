#!/usr/bin/env python3
"""
Test GPU validation for subtitle and watermark removal modes.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_gpu_utils():
    """Test GPU utility functions."""
    print("=" * 60)
    print("Testing GPU Utils")
    print("=" * 60)

    from src.infrastructure.utils.gpu_utils import (
        check_gpu_available, get_gpu_info, log_gpu_status
    )

    # Check GPU availability
    gpu_available = check_gpu_available()
    print(f"GPU Available: {gpu_available}")

    # Get GPU info
    gpu_info = get_gpu_info()
    if gpu_info:
        print(f"GPU Info: {gpu_info}")
    else:
        print("No GPU info available")

    # Log status
    log_gpu_status()

    return gpu_available


def test_subtitle_remover_creation():
    """Test subtitle remover factory with GPU check."""
    print("\n" + "=" * 60)
    print("Testing Subtitle Remover Creation (should fail without GPU)")
    print("=" * 60)

    from src.application.factories import ProcessorFactory
    from src.domain.exceptions import GPURequiredError

    factory = ProcessorFactory()

    try:
        remover = factory.create_subtitle_remover(
            lang='en',
            roi='bottom'
        )
        print("✅ Subtitle remover created successfully")
        return True
    except GPURequiredError as e:
        print(f"❌ GPU Required Error (expected without GPU):")
        print(f"   {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_watermark_remover_creation():
    """Test watermark remover factory with GPU check."""
    print("\n" + "=" * 60)
    print("Testing Watermark Remover Creation (should fail without GPU)")
    print("=" * 60)

    from src.application.factories import ProcessorFactory
    from src.domain.exceptions import GPURequiredError

    factory = ProcessorFactory()

    try:
        remover = factory.create_watermark_remover(
            roi='top-right'
        )
        print("✅ Watermark remover created successfully")
        return True
    except GPURequiredError as e:
        print(f"❌ GPU Required Error (expected without GPU):")
        print(f"   {str(e)}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function."""
    print("\n🧪 GPU Validation Test Suite\n")

    # Test 1: GPU utils
    gpu_available = test_gpu_utils()

    # Test 2: Subtitle remover
    subtitle_ok = test_subtitle_remover_creation()

    # Test 3: Watermark remover
    watermark_ok = test_watermark_remover_creation()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"GPU Available: {gpu_available}")
    print(f"Subtitle Remover: {'✅ Created' if subtitle_ok else '❌ Blocked (no GPU)'}")
    print(f"Watermark Remover: {'✅ Created' if watermark_ok else '❌ Blocked (no GPU)'}")

    if gpu_available:
        if subtitle_ok and watermark_ok:
            print("\n✅ All tests passed! GPU validation is working correctly.")
            return 0
        else:
            print("\n⚠️  GPU available but processors failed to create.")
            return 1
    else:
        if not subtitle_ok and not watermark_ok:
            print("\n✅ GPU validation working! Processors correctly blocked without GPU.")
            return 0
        else:
            print("\n❌ FAIL: Processors created without GPU (validation not working!)")
            return 1


if __name__ == '__main__':
    sys.exit(main())

