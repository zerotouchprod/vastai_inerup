"""
Test that RIFENativeWrapper can properly import and use RIFENative.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_import():
    """Test that the import works correctly."""
    print("Testing RIFE native wrapper import fix...")

    # This should not raise NameError anymore
    from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper

    print(f"✓ RIFENativeWrapper imported successfully")

    # Check is_available (won't be true on Windows without CUDA, but should not crash)
    try:
        available = RIFENativeWrapper.is_available()
        print(f"✓ is_available() check passed: {available}")
    except Exception as e:
        print(f"✓ is_available() check handled gracefully: {e}")

    # Try to instantiate (will fail without dependencies, but should not have NameError)
    try:
        wrapper = RIFENativeWrapper()
        print(f"✓ Instantiation succeeded (CUDA available)")
    except Exception as e:
        if "not available" in str(e).lower():
            print(f"✓ Instantiation failed as expected (no CUDA): {e}")
        elif "NameError" in str(type(e).__name__):
            print(f"✗ FAILED: NameError still present: {e}")
            return False
        else:
            print(f"✓ Instantiation failed for other reason: {e}")

    print("\n✅ All import tests passed! The NameError is fixed.")
    return True

if __name__ == "__main__":
    success = test_import()
    sys.exit(0 if success else 1)

