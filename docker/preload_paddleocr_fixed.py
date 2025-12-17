#!/usr/bin/env python3
"""
Pre-download PaddleOCR models for faster startup.
Simplified version to avoid Illegal instruction errors.
"""

import os
import sys
import logging

# Disable verbose logging
logging.getLogger().setLevel(logging.ERROR)

def main():
    try:
        # Set environment variables before importing paddle
        os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'
        os.environ['LOG_LEVEL'] = 'ERROR'
        
        print('Attempting to import PaddleOCR...')
        from paddleocr import PaddleOCR
        
        print('Initializing PaddleOCR English model (this will download models)...')
        # Use minimal configuration
        ocr = PaddleOCR(
            lang='en',
            use_angle_cls=False,
            show_log=False,
            use_gpu=False
        )
        print('✓ PaddleOCR English models initialized')
        
        # Check if model directory was created
        model_dir = os.path.expanduser('~/.paddlex/official_models')
        if os.path.exists(model_dir):
            print(f'Model directory created: {model_dir}')
            # List a few files to verify
            import glob
            files = glob.glob(os.path.join(model_dir, '**', '*.pdparams'), recursive=True)
            if files:
                print(f'Found {len(files)} model files')
            else:
                print('Warning: No model files found, but directory exists')
        else:
            print('Warning: Model directory not created yet')
        
        return True
        
    except Exception as e:
        print(f'Warning: PaddleOCR initialization failed: {e}')
        print('Models will be downloaded on first run instead')
        return True  # Return True anyway to not fail the build

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
