#!/usr/bin/env python3
"""
Pre-download PaddleOCR models for faster startup.
This script is executed during Docker build to download English and Russian models.
"""

import sys
sys.path.insert(0, '/opt/venv/lib/python3.10/site-packages')

import os
import logging
logging.basicConfig(level=logging.INFO)

def main():
    try:
        from paddleocr import PaddleOCR
        # Initialize PaddleOCR with English model to trigger model download
        # This will download models to ~/.paddlex/official_models
        print('Initializing PaddleOCR English model...')
        ocr = PaddleOCR(lang='en')
        print('✓ PaddleOCR English models downloaded')
        
        # Also download Russian model if needed
        print('Initializing PaddleOCR Russian model...')
        ocr_ru = PaddleOCR(lang='ru')
        print('✓ PaddleOCR Russian models downloaded')
        
        # Verify that model files exist
        model_dir = os.path.expanduser('~/.paddlex/official_models')
        if os.path.exists(model_dir):
            print(f'Model directory: {model_dir}')
            import subprocess
            result = subprocess.run(['find', model_dir, '-type', 'f', '-name', '*.pdparams'], 
                                    capture_output=True, text=True)
            files = result.stdout.strip().split('\n')
            if files and files[0]:
                print(f'Found {len(files)} model files')
                for f in files[:5]:
                    print(f'  {os.path.basename(f)}')
            else:
                print('Warning: No model files found')
        else:
            print('Warning: Model directory does not exist')
        
        # Test with a simple image to ensure models work
        import cv2
        import numpy as np
        img = np.zeros((100, 200, 3), dtype=np.uint8)
        img.fill(255)
        cv2.putText(img, 'Test', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        result = ocr.ocr(img)
        print('✓ PaddleOCR test successful')
        return True
    except Exception as e:
        print('Error: PaddleOCR model pre-download failed:', e)
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
