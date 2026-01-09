#!/usr/bin/env python3
"""Quick test script to verify ROI parsing."""

import sys
sys.path.insert(0, '/home/fevr/PycharmProjects/vastai_inerup')

from src.infrastructure.image_processing.geometry import resolve_roi

# Test case: '0.0,0.5,1.0,0.4'
img_w, img_h = 1920, 1080

print("Testing ROI format: x,y,w,h")
print(f"Frame size: {img_w}x{img_h}")
print()

roi_str = '0.0,0.5,1.0,0.4'
print(f"Input ROI: '{roi_str}'")
print("Expected interpretation:")
print("  x = 0.0 (start at left edge, 0% of width)")
print("  y = 0.5 (start at 50% of height)")
print("  w = 1.0 (span 100% of width)")
print("  h = 0.4 (span 40% of height)")
print()

x, y, w, h = resolve_roi(roi_str, img_w, img_h)

print(f"Parsed result:")
print(f"  x = {x} (expected: 0)")
print(f"  y = {y} (expected: {int(0.5 * img_h)} = 540)")
print(f"  w = {w} (expected: {img_w} = 1920)")
print(f"  h = {h} (expected: {int(0.4 * img_h)} = 432)")
print()

# Calculate coverage
y_start_pct = y / img_h
y_end_pct = (y + h) / img_h

print(f"Region coverage:")
print(f"  Starts at: {y_start_pct:.1%} of height")
print(f"  Ends at: {y_end_pct:.1%} of height")
print(f"  Covers: {y_start_pct:.1%} to {y_end_pct:.1%}")
print()

# Verify
success = True
if x != 0:
    print(f"❌ FAIL: x should be 0, got {x}")
    success = False
if y != 540:
    print(f"❌ FAIL: y should be 540, got {y}")
    success = False
if w != 1920:
    print(f"❌ FAIL: w should be 1920, got {w}")
    success = False
if h != 432:
    print(f"❌ FAIL: h should be 432, got {h}")
    success = False

if success:
    print("✅ All checks passed!")
else:
    print("❌ Test failed!")
    sys.exit(1)

