#!/usr/bin/env python3
import os
import sys

def check_paddleocr():
    model_dir = os.path.expanduser('~/.paddlex/official_models')
    if not os.path.exists(model_dir):
        print(f"PaddleOCR model directory not found: {model_dir}")
        return False
    import subprocess
    result = subprocess.run(['find', model_dir, '-type', 'f', '-name', '*.pdparams'], 
                            capture_output=True, text=True)
    files = result.stdout.strip().split('\n')
    if not files or not files[0]:
        print("No .pdparams files found")
        return False
    print(f"Found {len(files)} model files")
    for f in files[:5]:
        print(f"  {os.path.basename(f)}")
    return True

def check_propainter():
    propainter_root = os.getenv('PROPAINTER_ROOT', '/opt/ProPainter')
    weights = ['ProPainter.pth', 'raft-things.pth', 'recurrent_flow_completion.pth']
    for w in weights:
        path = os.path.join(propainter_root, 'weights', w)
        if not os.path.exists(path):
            print(f"Missing ProPainter weight: {path}")
            return False
    print("All ProPainter weights present")
    return True

if __name__ == '__main__':
    print("Checking model presence...")
    paddle_ok = check_paddleocr()
    propainter_ok = check_propainter()
    if paddle_ok and propainter_ok:
        print("All models are present.")
        sys.exit(0)
    else:
        print("Some models are missing.")
        sys.exit(1)
