"""
Unit tests for ROI geometry functions.
Tests multi-ROI parsing, watermark presets, and coordinate resolution.
"""

import pytest
from src.infrastructure.image_processing.geometry import (
    resolve_roi, resolve_multi_roi
)


class TestROIResolution:
    """Test ROI string resolution to pixel coordinates."""

    def test_resolve_roi_bottom_preset(self):
        """Test 'bottom' preset ROI (60% of height from bottom)."""
        x, y, w, h = resolve_roi('bottom', 1920, 1080)
        assert x == 0
        assert w == 1920
        assert h == int(1080 * 0.60)  # Bottom 60%
        assert y == 1080 - h

    def test_resolve_roi_top_preset(self):
        """Test 'top' preset ROI."""
        x, y, w, h = resolve_roi('top', 1920, 1080)
        assert x == 0
        assert y == 0
        assert w == 1920
        assert h == int(1080 * 0.30)  # Top 30%

    def test_resolve_roi_full_preset(self):
        """Test 'full' preset ROI."""
        x, y, w, h = resolve_roi('full', 1920, 1080)
        assert x == 0
        assert y == 0
        assert w == 1920
        assert h == 1080

    def test_resolve_roi_top_left_watermark(self):
        """Test 'top-left' watermark preset."""
        x, y, w, h = resolve_roi('top-left', 1920, 1080)
        assert x == 0
        assert y == 0
        assert w == int(1920 * 0.2)  # 20% of width
        assert h == int(1080 * 0.2)  # 20% of height

    def test_resolve_roi_top_right_watermark(self):
        """Test 'top-right' watermark preset."""
        x, y, w, h = resolve_roi('top-right', 1920, 1080)
        assert x == int(1920 * 0.8)
        assert y == 0
        assert w == 1920 - x
        assert h == int(1080 * 0.2)

    def test_resolve_roi_bottom_left_watermark(self):
        """Test 'bottom-left' watermark preset."""
        x, y, w, h = resolve_roi('bottom-left', 1920, 1080)
        assert x == 0
        assert y == int(1080 * 0.8)
        assert w == int(1920 * 0.2)
        assert h == 1080 - y

    def test_resolve_roi_bottom_right_watermark(self):
        """Test 'bottom-right' watermark preset."""
        x, y, w, h = resolve_roi('bottom-right', 1920, 1080)
        assert x == int(1920 * 0.8)
        assert y == int(1080 * 0.8)
        assert w == 1920 - x
        assert h == 1080 - y

    def test_resolve_roi_center_watermark(self):
        """Test 'center' watermark preset."""
        x, y, w, h = resolve_roi('center', 1920, 1080)
        assert x == int(1920 * 0.3)
        assert y == int(1080 * 0.3)
        assert w == int(1920 * 0.4)
        assert h == int(1080 * 0.4)

    def test_resolve_roi_custom_coordinates(self):
        """Test custom coordinate ROI."""
        # "0.1,0.2,0.5,0.3" -> 10% from left, 20% from top, 50% width, 30% height
        x, y, w, h = resolve_roi('0.1,0.2,0.5,0.3', 1000, 1000)
        assert x == 100
        assert y == 200
        assert w == 500
        assert h == 300

    def test_resolve_roi_invalid_fallback(self):
        """Test fallback behavior for invalid ROI string."""
        x, y, w, h = resolve_roi('invalid_preset', 1920, 1080)
        # Should fallback to 'bottom'
        assert x == 0
        assert w == 1920


class TestMultiROI:
    """Test multi-ROI parsing for watermark removal."""

    def test_resolve_multi_roi_single_preset(self):
        """Test single preset returns list with one ROI."""
        rois = resolve_multi_roi('top-right', 1920, 1080)
        assert len(rois) == 1
        x, y, w, h = rois[0]
        assert x == int(1920 * 0.8)

    def test_resolve_multi_roi_two_presets(self):
        """Test two presets separated by comma."""
        rois = resolve_multi_roi('top-right,bottom-left', 1920, 1080)
        assert len(rois) == 2

        # First ROI: top-right
        x1, y1, w1, h1 = rois[0]
        assert x1 == int(1920 * 0.8)
        assert y1 == 0

        # Second ROI: bottom-left
        x2, y2, w2, h2 = rois[1]
        assert x2 == 0
        assert y2 == int(1080 * 0.8)

    def test_resolve_multi_roi_three_presets(self):
        """Test three watermark zones."""
        rois = resolve_multi_roi('top-left,top-right,bottom-right', 1920, 1080)
        assert len(rois) == 3

    def test_resolve_multi_roi_single_coordinates(self):
        """Test single coordinate string (not multi-preset)."""
        rois = resolve_multi_roi('0.1,0.2,0.5,0.3', 1000, 1000)
        assert len(rois) == 1
        x, y, w, h = rois[0]
        assert x == 100
        assert y == 200

    def test_resolve_multi_roi_with_spaces(self):
        """Test multi-preset with spaces around commas."""
        rois = resolve_multi_roi('top-right , bottom-left', 1920, 1080)
        assert len(rois) == 2


class TestROIEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_resolve_roi_small_dimensions(self):
        """Test ROI with very small frame dimensions."""
        x, y, w, h = resolve_roi('bottom', 100, 100)
        assert 0 <= x < 100
        assert 0 <= y < 100
        assert w > 0
        assert h > 0

    def test_resolve_roi_case_insensitive(self):
        """Test that presets are case-insensitive."""
        roi1 = resolve_roi('BOTTOM', 1920, 1080)
        roi2 = resolve_roi('bottom', 1920, 1080)
        assert roi1 == roi2

    def test_resolve_roi_with_whitespace(self):
        """Test ROI string with leading/trailing whitespace."""
        x, y, w, h = resolve_roi('  bottom  ', 1920, 1080)
        assert w == 1920


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

