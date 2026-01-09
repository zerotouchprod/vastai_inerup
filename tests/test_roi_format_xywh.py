"""
Test ROI parsing in x,y,w,h format.
Ensures that ROI string '0.0,0.5,1.0,0.4' is correctly interpreted as:
- x=0.0 (start at left edge, 0% of width)
- y=0.5 (start at 50% of height from top)
- w=1.0 (span full width, 100%)
- h=0.4 (span 40% of height)

This creates a region from 50% to 90% of the frame height, full width.
"""

import pytest
from src.infrastructure.image_processing.geometry import resolve_roi, resolve_multi_roi


def test_roi_xywh_format():
    """Test x,y,w,h format parsing."""
    # Test case: '0.0,0.5,1.0,0.4'
    # Expected: x=0, y=540 (50% of 1080), w=1920, h=432 (40% of 1080)
    img_w, img_h = 1920, 1080

    x, y, w, h = resolve_roi('0.0,0.5,1.0,0.4', img_w, img_h)

    assert x == 0, f"Expected x=0, got {x}"
    assert y == 540, f"Expected y=540 (50% of 1080), got {y}"
    assert w == 1920, f"Expected w=1920 (full width), got {w}"
    assert h == 432, f"Expected h=432 (40% of 1080), got {h}"

    # Verify the region covers the bottom half (50% to 90%)
    y_start_pct = y / img_h
    y_end_pct = (y + h) / img_h

    assert abs(y_start_pct - 0.5) < 0.01, f"Region should start at 50%, got {y_start_pct:.2%}"
    assert abs(y_end_pct - 0.9) < 0.01, f"Region should end at 90%, got {y_end_pct:.2%}"


def test_roi_bottom_preset():
    """Test 'bottom' preset (should give bottom 60%)."""
    img_w, img_h = 1920, 1080

    x, y, w, h = resolve_roi('bottom', img_w, img_h)

    # Bottom 60% means: start at 40% from top, span 60% height
    expected_y = int(img_h * 0.4)  # Start at 40%
    expected_h = int(img_h * 0.6)  # Height of 60%

    assert x == 0, f"Expected x=0, got {x}"
    assert y == expected_y, f"Expected y={expected_y}, got {y}"
    assert w == img_w, f"Expected w={img_w}, got {w}"
    assert h == expected_h, f"Expected h={expected_h}, got {h}"


def test_roi_conversion_internal():
    """Test that SubtitleRemoverService correctly converts x,y,w,h to internal bbox format."""
    from src.services.cleaner_service import SubtitleRemoverService
    from unittest.mock import MagicMock

    # Create mock objects
    mock_mask_service = MagicMock()
    mock_inpainter = MagicMock()

    # Create service with custom ROI
    service = SubtitleRemoverService(
        mask_service=mock_mask_service,
        inpainter=mock_inpainter,
        lang='en',
        roi_factor='0.0,0.5,1.0,0.4'
    )

    # Check internal representation
    assert service.roi_mode == 'bbox', "Should use bbox mode for custom ROI"

    x1, y1, x2, y2 = service.roi_bbox

    # Verify conversion: x,y,w,h -> x1,y1,x2,y2
    # Input: x=0.0, y=0.5, w=1.0, h=0.4
    # Expected: x1=0.0, y1=0.5, x2=1.0 (0.0+1.0), y2=0.9 (0.5+0.4)
    assert abs(x1 - 0.0) < 0.01, f"Expected x1=0.0, got {x1}"
    assert abs(y1 - 0.5) < 0.01, f"Expected y1=0.5, got {y1}"
    assert abs(x2 - 1.0) < 0.01, f"Expected x2=1.0, got {x2}"
    assert abs(y2 - 0.9) < 0.01, f"Expected y2=0.9, got {y2}"


def test_roi_description():
    """Test ROI description format."""
    from src.services.cleaner_service import SubtitleRemoverService
    from unittest.mock import MagicMock

    mock_mask_service = MagicMock()
    mock_inpainter = MagicMock()

    service = SubtitleRemoverService(
        mask_service=mock_mask_service,
        inpainter=mock_inpainter,
        lang='en',
        roi_factor='0.0,0.5,1.0,0.4'
    )

    desc = service._get_roi_description()

    # Should show original x,y,w,h format
    assert 'x=0.00' in desc, f"Description should contain x=0.00, got: {desc}"
    assert 'y=0.50' in desc, f"Description should contain y=0.50, got: {desc}"
    assert 'w=1.00' in desc, f"Description should contain w=1.00, got: {desc}"
    assert 'h=0.40' in desc, f"Description should contain h=0.40, got: {desc}"


def test_roi_multi_zone():
    """Test multi-zone ROI parsing (for watermarks)."""
    img_w, img_h = 1920, 1080

    # Single ROI in x,y,w,h format
    result = resolve_multi_roi('0.0,0.5,1.0,0.4', img_w, img_h)

    assert len(result) == 1, "Should return single ROI"
    x, y, w, h = result[0]
    assert x == 0
    assert y == 540  # 50% of 1080
    assert w == 1920
    assert h == 432  # 40% of 1080


def test_roi_edge_cases():
    """Test edge cases for ROI parsing."""
    img_w, img_h = 1920, 1080

    # Full frame
    x, y, w, h = resolve_roi('full', img_w, img_h)
    assert x == 0 and y == 0 and w == img_w and h == img_h

    # Top-right corner preset (for watermarks)
    x, y, w, h = resolve_roi('top-right', img_w, img_h)
    assert x > img_w * 0.5, "top-right should be in right half"
    assert y == 0, "top-right should be at top"

    # Custom: narrow vertical strip (e.g., for side watermarks)
    x, y, w, h = resolve_roi('0.8,0.0,0.2,1.0', img_w, img_h)
    expected_x = int(0.8 * img_w)
    expected_w = int(0.2 * img_w)
    assert abs(x - expected_x) <= 1, f"Expected x≈{expected_x}, got {x}"
    assert abs(w - expected_w) <= 1, f"Expected w≈{expected_w}, got {w}"
    assert y == 0
    assert h == img_h


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

