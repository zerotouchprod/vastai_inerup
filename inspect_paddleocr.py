import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

import sys
sys.path.insert(0, '.')

import inspect

try:
    from paddleocr import PaddleOCR
    print("PaddleOCR imported successfully")
    sig = inspect.signature(PaddleOCR.__init__)
    print("Signature of PaddleOCR.__init__:")
    print(sig)
    print("\nParameters:")
    for param_name, param in sig.parameters.items():
        print(f"  {param_name}: {param}")
except ImportError as e:
    print(f"Import error: {e}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
