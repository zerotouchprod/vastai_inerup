import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

import sys
sys.path.insert(0, '.')

print('Importing PaddleOCR...')
from paddleocr import PaddleOCR

print('Creating OCR instance...')
ocr = PaddleOCR(lang='ru', text_det_thresh=0.1, text_det_box_thresh=0.1, text_rec_score_thresh=0.01)

print('OCR created successfully')
print('Testing on sample image...')

import cv2
import numpy as np

img = cv2.imread('test_img/frame_000001.png')
if img is None:
    print('Failed to load image')
else:
    print(f'Image shape: {img.shape}')
    result = ocr.ocr(img, cls=True, rec=True)
    print(f'Result type: {type(result)}')
    if result and result[0]:
        print(f'Number of detections: {len(result[0])}')
        for det in result[0][:2]:
            print(f'  Detection: {det}')
    else:
        print('No detections')

print('Done')
