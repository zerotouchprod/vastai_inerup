#!/usr/bin/env python3
"""
Pre-download PaddleOCR models for faster startup.
This script is executed during Docker build to download English and Russian models.
"""

import sys
import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
sys.path.insert(0, '/opt/venv/lib/python3.10/site-packages')

try:
    from paddleocr import PaddleOCR
    # Initialize PaddleOCR with English model to trigger model download
    # This will download models to ~/.paddlex/official_models
    ocr = PaddleOCR(lang='en')
    print('✓ PaddleOCR English models downloaded')
    
    # Also download Russian model if needed
    ocr_ru = PaddleOCR(lang='ru')
    print('✓ PaddleOCR Russian models downloaded')
    
    # Test with a simple image to ensure models work
    import cv2
    import numpy as np
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    img.fill(255)
    cv2.putText(img, 'Test', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    result = ocr.ocr(img)
    print('✓ PaddleOCR test successful')
except Exception as e:
    print('Warning: PaddleOCR model pre-download failed:', e)
    print('Models will be downloaded on first run instead')
