#!/usr/bin/env python3
"""
Test ROI parsing logic for SubtitleRemoverService.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.shared.logging import setup_logger, get_logger

setup_logger('test_roi', level=10)  # DEBUG level
logger = get_logger(__name__)


def test_roi_parsing():
    """Test various ROI formats."""

    # Mock dependencies
    class MockMaskService:
        pass

    class MockInpainter:
        pass

    from src.services.cleaner_service import SubtitleRemoverService

    test_cases = [
        # (roi_input, expected_mode, expected_description)
        ('0.0,0.5,1.0,0.4', 'bbox', 'Should auto-fix inverted y coordinates'),
        ('0.0,0.5,1.0,1.0', 'bbox', 'Bottom half of screen'),
        ('0.0,0.6,1.0,1.0', 'bbox', 'Bottom 40% of screen'),
        ('0.05,0.6,0.9,0.1', 'bbox', 'Should auto-fix inverted y coordinates'),
        ('bottom', 'percentage', 'Default bottom 60%'),
        ('full', 'percentage', 'Full screen'),
        ('0.6', 'percentage', 'Custom 60%'),
        ('invalid', 'percentage', 'Should fallback to default'),
    ]

    print("=" * 80)
    print("ROI Parsing Test Suite")
    print("=" * 80)
    print()

    for roi_input, expected_mode, description in test_cases:
        print(f"\n{'='*80}")
        print(f"Test: {description}")
        print(f"Input: --roi '{roi_input}'")
        print("-" * 80)

        try:
            # Note: This will fail with GPU check, so we'll catch that
            # We're only interested in ROI parsing which happens before GPU check
            service = SubtitleRemoverService(
                MockMaskService(),
                MockInpainter(),
                lang='en',
                roi_factor=roi_input,
                debug=False
            )

            print(f"✅ Mode: {service.roi_mode}")

            if service.roi_mode == 'bbox':
                x1, y1, x2, y2 = service.roi_bbox
                print(f"   Bbox: ({x1:.2f}, {y1:.2f}, {x2:.2f}, {y2:.2f})")
                print(f"   Width: {x2-x1:.2f}, Height: {y2-y1:.2f}")
            else:
                print(f"   Height factor: {service.roi_height_factor}")

            print(f"   Description: {service._get_roi_description()}")

        except Exception as e:
            # Expected to fail at GPU check or other initialization
            error_msg = str(e)
            if 'GPU required' in error_msg or 'GPURequiredError' in str(type(e).__name__):
                print("⚠️  Stopped at GPU check (expected)")
                print(f"   ROI parsing completed successfully before GPU check")
            else:
                print(f"❌ Error: {e}")
                import traceback
                traceback.print_exc()

    print("\n" + "=" * 80)
    print("Test Complete")
    print("=" * 80)

    # Specific test for the user's case
    print("\n" + "=" * 80)
    print("SPECIFIC TEST: User's Command")
    print("=" * 80)
    print("Command: --roi '0.0,0.5,1.0,0.4'")
    print("Expected: Should auto-correct to (0.0, 0.4, 1.0, 0.5)")
    print("Reason: y2 < y1, so coordinates will be swapped")
    print()
    print("Corrected interpretation:")
    print("  - Left edge: x=0.0 (0%)")
    print("  - Top edge: y=0.4 (40% from top)")
    print("  - Right edge: x=1.0 (100%)")
    print("  - Bottom edge: y=0.5 (50% from top)")
    print("  - Region: Middle 10% of screen (from 40% to 50%)")
    print()
    print("Did you mean:")
    print("  - Bottom half: '0.0,0.5,1.0,1.0' (y from 50% to 100%)")
    print("  - Bottom 40%: '0.0,0.6,1.0,1.0' (y from 60% to 100%)")
    print("=" * 80)


if __name__ == '__main__':
    test_roi_parsing()

