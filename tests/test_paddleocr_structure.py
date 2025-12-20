#!/usr/bin/env python3
"""Test PaddleOCR result structure."""

import sys
import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

import cv2
import numpy as np
from paddleocr import PaddleOCR

print("Creating test image...")
# Create a simple test image with text
img = np.zeros((200, 400, 3), dtype=np.uint8)
img.fill(255)  # White background
cv2.putText(img, 'Hello World', (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
cv2.putText(img, 'Subtitle test', (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

print("Initializing PaddleOCR...")
ocr = PaddleOCR(lang='en')

print("Running OCR...")
result = ocr.ocr(img)

print("\n=== OCR Result Structure ===")
print(f"Type of result: {type(result)}")
print(f"Result: {result}")

if result:
    print(f"\nLength of result: {len(result)}")
    
    if result[0]:
        print(f"\nFirst detection (result[0][0]):")
        det = result[0][0]
        print(f"  Type: {type(det)}")
        print(f"  Value: {det}")
        print(f"  Length: {len(det)}")
        
        for i, item in enumerate(det):
            print(f"    Item {i}: {repr(item)}, type: {type(item)}")
            
        # Try to parse like our code does
        print("\n  Trying to parse coordinates and text:")
        if len(det) >= 1:
            print(f"    Coordinates (det[0]): {det[0]}")
            print(f"    Type of coordinates: {type(det[0])}")
            
        if len(det) >= 2:
            print(f"    Text/confidence (det[1]): {det[1]}")
            print(f"    Type of text/confidence: {type(det[1])}")
            
            if isinstance(det[1], (list, tuple)):
                print(f"    Length of text/confidence: {len(det[1])}")
                if len(det[1]) >= 1:
                    print(f"    Text: {det[1][0]}")
                if len(det[1]) >= 2:
                    print(f"    Confidence: {det[1][1]}")
            else:
                print(f"    Text/confidence is not list/tuple, trying to access:")
                try:
                    print(f"    det[1][0]: {det[1][0]}")
                    print(f"    det[1][1]: {det[1][1]}")
                except Exception as e:
                    print(f"    Error accessing det[1][0] or det[1][1]: {e}")
else:
    print("No result returned")

print("\n=== Testing with empty image (no text) ===")
empty_img = np.zeros((100, 100, 3), dtype=np.uint8)
empty_img.fill(255)
empty_result = ocr.ocr(empty_img)
print(f"Empty image result: {empty_result}")
print(f"Type: {type(empty_result)}")
if empty_result:
    print(f"Length: {len(empty_result)}")
    if empty_result[0] is None:
        print("Result[0] is None (no text detected)")
    else:
        print(f"Result[0]: {empty_result[0]}")
