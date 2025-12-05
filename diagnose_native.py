"""
Diagnostic script to check why native RIFE isn't being used in container.
Run this in the container to see what's happening.
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

print("="*60)
print("RIFE Native Availability Diagnostic")
print("="*60)
print()

# 1. Check environment
print("1. Environment:")
print(f"   USE_NATIVE_PROCESSORS={os.environ.get('USE_NATIVE_PROCESSORS', 'not set')}")
print()

# 2. Check torch
print("2. PyTorch:")
try:
    import torch
    print(f"   ✓ PyTorch imported: {torch.__version__}")
    print(f"   CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   CUDA device: {torch.cuda.get_device_name(0)}")
except ImportError as e:
    print(f"   ✗ PyTorch import failed: {e}")
    sys.exit(1)
print()

# 3. Try to import RIFENative
print("3. RIFENative import:")
try:
    from infrastructure.processors.rife.native import RIFENative
    print(f"   ✓ RIFENative imported successfully")
except ImportError as e:
    print(f"   ✗ RIFENative import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# 4. Try to import RIFENativeWrapper
print("4. RIFENativeWrapper import:")
try:
    from infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
    print(f"   ✓ RIFENativeWrapper imported successfully")
except ImportError as e:
    print(f"   ✗ RIFENativeWrapper import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
print()

# 5. Check is_available()
print("5. RIFENativeWrapper.is_available():")
try:
    available = RIFENativeWrapper.is_available()
    print(f"   Result: {available}")
    if not available:
        print(f"   ✗ is_available() returned False - this is why bash wrapper is used!")
    else:
        print(f"   ✓ is_available() returned True")
except Exception as e:
    print(f"   ✗ is_available() raised exception: {e}")
    import traceback
    traceback.print_exc()
print()

# 6. Try to create instance
print("6. Try to create RIFENativeWrapper instance:")
try:
    wrapper = RIFENativeWrapper()
    print(f"   ✓ RIFENativeWrapper instance created successfully")
    print(f"   Type: {type(wrapper)}")
except Exception as e:
    print(f"   ✗ Failed to create instance: {e}")
    import traceback
    traceback.print_exc()
print()

# 7. Check factory
print("7. ProcessorFactory with use_native=True:")
try:
    from application.factories import ProcessorFactory
    factory = ProcessorFactory(use_native=True)
    print(f"   ✓ Factory created with use_native=True")

    # Try to create interpolator
    print("   Creating interpolator...")
    interpolator = factory.create_interpolator(prefer='auto')
    print(f"   ✓ Interpolator created: {type(interpolator).__name__}")
    print(f"   Module: {type(interpolator).__module__}")

    is_native = 'native_wrapper' in type(interpolator).__module__
    is_bash = 'pytorch_wrapper' in type(interpolator).__module__

    if is_native:
        print(f"   ✓ Using NATIVE processor!")
    elif is_bash:
        print(f"   ✗ Using BASH wrapper - this is the problem!")
    else:
        print(f"   ? Unknown processor type")

except Exception as e:
    print(f"   ✗ Factory test failed: {e}")
    import traceback
    traceback.print_exc()
print()

print("="*60)
print("Diagnostic complete!")
print("="*60)

