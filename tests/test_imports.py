#!/usr/bin/env python3
import sys
import os

def test_imports():
    try:
        import paddleocr
        print("✓ paddleocr imported")
    except Exception as e:
        print(f"✗ paddleocr import failed: {e}")
        return False
    try:
        from paddleocr import PaddleOCR
        print("✓ PaddleOCR class imported")
    except Exception as e:
        print(f"✗ PaddleOCR class import failed: {e}")
        return False
    try:
        import torch
        print(f"✓ torch imported, version {torch.__version__}")
    except Exception as e:
        print(f"✗ torch import failed: {e}")
        return False
    try:
        import cv2
        print(f"✓ cv2 imported, version {cv2.__version__}")
    except Exception as e:
        print(f"✗ cv2 import failed: {e}")
        return False
    try:
        sys.path.insert(0, '/opt/ProPainter')
        import inference_propainter
        print("✓ ProPainter inference module imported")
    except Exception as e:
        print(f"✗ ProPainter import failed: {e}")
        return False
    return True

if __name__ == '__main__':
    success = test_imports()
    sys.exit(0 if success else 1)
