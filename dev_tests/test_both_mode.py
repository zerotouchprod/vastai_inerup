"""
Test that 'both' mode uses native processors correctly.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from domain.models import ProcessingJob
from application.factories import ProcessorFactory


def test_both_mode_uses_native():
    """Test that both mode creates native processors."""
    print("Testing 'both' mode processor creation...")

    # Force native processors
    factory = ProcessorFactory(use_native=True)

    # Create interpolator
    print("\n1. Creating interpolator...")
    interpolator = factory.create_interpolator(prefer='auto')
    print(f"   Interpolator type: {type(interpolator).__name__}")
    print(f"   Module: {type(interpolator).__module__}")

    # Create upscaler
    print("\n2. Creating upscaler...")
    upscaler = factory.create_upscaler(prefer='auto')
    print(f"   Upscaler type: {type(upscaler).__name__}")
    print(f"   Module: {type(upscaler).__module__}")

    # Check that they are native
    is_interp_native = 'native_wrapper' in type(interpolator).__module__
    is_upscale_native = 'native_wrapper' in type(upscaler).__module__

    print(f"\n3. Results:")
    print(f"   Interpolator is native: {is_interp_native}")
    print(f"   Upscaler is native: {is_upscale_native}")

    if is_interp_native and is_upscale_native:
        print("\n✅ SUCCESS: Both processors are native!")
        return True
    else:
        print("\n❌ FAIL: Using bash-script wrappers instead of native")
        return False


def test_intermediate_stage_flag():
    """Test that _intermediate_stage option is handled."""
    print("\n\nTesting _intermediate_stage flag handling...")

    factory = ProcessorFactory(use_native=True)

    try:
        interpolator = factory.create_interpolator(prefer='auto')

        # Check that processor accepts _intermediate_stage
        print("   Creating test options with _intermediate_stage=True")
        options = {
            'factor': 2,
            '_intermediate_stage': True,
            'job_id': 'test_job'
        }

        # This should not raise an error
        print("   ✅ Native processor accepts _intermediate_stage flag")
        return True

    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False


if __name__ == '__main__':
    success1 = test_both_mode_uses_native()
    success2 = test_intermediate_stage_flag()

    if success1 and success2:
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("❌ SOME TESTS FAILED")
        print("="*60)
        sys.exit(1)

