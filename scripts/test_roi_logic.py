#!/usr/bin/env python3
"""
Test ROI logic for process_image.py
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import cv2
import numpy as np

# Create a test image
test_image = np.zeros((100, 200, 3), dtype=np.uint8)
test_image[:] = (100, 100, 100)  # Gray background

# Test the apply_roi function
from scripts.process_image import apply_roi

print("Testing ROI logic...")
print(f"Test image shape: {test_image.shape}")

# Test full ROI
cropped, ox, oy = apply_roi(test_image, 'full')
print(f"\n1. Full ROI:")
print(f"   Cropped shape: {cropped.shape}, offset_x={ox}, offset_y={oy}")
assert cropped.shape == test_image.shape, "Full ROI should return full image"
assert ox == 0 and oy == 0, "Full ROI should have zero offset"

# Test bottom ROI
cropped, ox, oy = apply_roi(test_image, 'bottom')
print(f"\n2. Bottom ROI:")
print(f"   Cropped shape: {cropped.shape}, offset_x={ox}, offset_y={oy}")
# Bottom 30% of 100px height = 30px, starting at y=70
assert cropped.shape[0] == 30, f"Bottom ROI should be 30px tall, got {cropped.shape[0]}"
assert cropped.shape[1] == 200, f"Bottom ROI should be full width, got {cropped.shape[1]}"
assert oy == 70, f"Bottom ROI should have offset_y=70, got {oy}"

# Test top ROI
cropped, ox, oy = apply_roi(test_image, 'top')
print(f"\n3. Top ROI:")
print(f"   Cropped shape: {cropped.shape}, offset_x={ox}, offset_y={oy}")
# Top 30% of 100px height = 30px
assert cropped.shape[0] == 30, f"Top ROI should be 30px tall, got {cropped.shape[0]}"
assert cropped.shape[1] == 200, f"Top ROI should be full width, got {cropped.shape[1]}"
assert oy == 0, f"Top ROI should have offset_y=0, got {oy}"

# Test custom ROI
cropped, ox, oy = apply_roi(test_image, '0.1,0.2,0.5,0.3')
print(f"\n4. Custom ROI (0.1,0.2,0.5,0.3):")
print(f"   Cropped shape: {cropped.shape}, offset_x={ox}, offset_y={oy}")
# x=0.1*200=20, y=0.2*100=20, w=0.5*200=100, h=0.3*100=30
assert ox == 20, f"Custom ROI should have offset_x=20, got {ox}"
assert oy == 20, f"Custom ROI should have offset_y=20, got {oy}"
assert cropped.shape[0] == 30, f"Custom ROI should be 30px tall, got {cropped.shape[0]}"
assert cropped.shape[1] == 100, f"Custom ROI should be 100px wide, got {cropped.shape[1]}"

# Test invalid ROI (should fallback to full)
cropped, ox, oy = apply_roi(test_image, 'invalid,format')
print(f"\n5. Invalid ROI (should fallback to full):")
print(f"   Cropped shape: {cropped.shape}, offset_x={ox}, offset_y={oy}")
assert cropped.shape == test_image.shape, "Invalid ROI should fallback to full image"
assert ox == 0 and oy == 0, "Invalid ROI should have zero offset"

print("\n✅ All ROI tests passed!")

# Test bbox coordinate adjustment
print("\n\nTesting bbox coordinate adjustment...")
test_bboxes = [[10, 10, 50, 30], [60, 20, 90, 40]]
offset_x, offset_y = 20, 30

adjusted_bboxes = []
for bbox in test_bboxes:
    x1, y1, x2, y2 = bbox
    adjusted_bboxes.append([
        x1 + offset_x,
        y1 + offset_y,
        x2 + offset_x,
        y2 + offset_y
    ])

print(f"Original bboxes: {test_bboxes}")
print(f"Offset: x={offset_x}, y={offset_y}")
print(f"Adjusted bboxes: {adjusted_bboxes}")

# Verify adjustments
for orig, adj in zip(test_bboxes, adjusted_bboxes):
    assert adj[0] == orig[0] + offset_x, f"x1 adjustment incorrect: {adj[0]} != {orig[0] + offset_x}"
    assert adj[1] == orig[1] + offset_y, f"y1 adjustment incorrect: {adj[1]} != {orig[1] + offset_y}"
    assert adj[2] == orig[2] + offset_x, f"x2 adjustment incorrect: {adj[2]} != {orig[2] + offset_x}"
    assert adj[3] == orig[3] + offset_y, f"y2 adjustment incorrect: {adj[3]} != {orig[3] + offset_y}"

print("✅ Bbox coordinate adjustment test passed!")

print("\n🎉 All tests completed successfully!")
