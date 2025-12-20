#!/usr/bin/env python3
"""
Verification script for auto-healing OCR initialization.
Ensures that MaskGeneratorService can handle rejected parameters (like use_gpu)
and still initialize with critical thresholds.
"""

import sys
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_auto_healing_with_rejected_use_gpu():
    """Test that when use_gpu is rejected, the service removes it and retries."""
    from src.services.mask_service import MaskGeneratorService

    # Mock PaddleOCR to raise TypeError on first call, succeed on second
    with patch('src.services.mask_service.PADDLE_AVAILABLE', True):
        with patch('src.services.mask_service.PaddleOCR') as MockPaddleOCR:
            # First call raises TypeError for use_gpu
            MockPaddleOCR.side_effect = [
                TypeError("__init__() got an unexpected keyword argument 'use_gpu'"),
                MagicMock()  # second call succeeds
            ]

            service = MaskGeneratorService(lang='en', use_gpu_for_ocr=True)

            # Should have been called twice
            assert MockPaddleOCR.call_count == 2, f"Expected 2 calls, got {MockPaddleOCR.call_count}"

            # First call should have use_gpu
            first_kwargs = MockPaddleOCR.call_args_list[0][1]
            assert 'use_gpu' in first_kwargs, "First call missing use_gpu"
            assert first_kwargs['use_gpu'] == True

            # Second call should NOT have use_gpu (removed)
            second_kwargs = MockPaddleOCR.call_args_list[1][1]
            assert 'use_gpu' not in second_kwargs, "Second call still has use_gpu (should be removed)"

            # Critical thresholds should still be present if not rejected
            # In our mock, they are not rejected, so they should stay
            critical_params = ['det_db_thresh', 'det_db_box_thresh', 'det_db_unclip_ratio', 'rec_thresh']
            for param in critical_params:
                assert param in second_kwargs, f"Critical param {param} missing after retry"

            print("✅ Auto-healing works: use_gpu rejected, removed, and retry succeeded.")

def test_all_critical_params_rejected_fallback():
    """Test that if all critical params are rejected, we still get an OCR instance (minimal config)."""
    from src.services.mask_service import MaskGeneratorService

    with patch('src.services.mask_service.PADDLE_AVAILABLE', True):
        with patch('src.services.mask_service.PaddleOCR') as MockPaddleOCR:
            # Simulate rejection of each critical param one by one
            # We'll mock side_effect to raise TypeError for each param sequentially
            # This is complex; instead we can just test that after stripping all params, we still get an instance.
            # Let's simulate that all params are rejected except the bare minimum.
            # We'll just mock that the first call raises TypeError for det_db_thresh, second for det_db_box_thresh, etc.
            # For simplicity, we'll just ensure the loop doesn't crash.
            # We'll create a mock that raises TypeError with different args each time.
            call_count = 0
            def side_effect(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise TypeError("unexpected keyword argument 'det_db_thresh'")
                elif call_count == 2:
                    raise TypeError("unexpected keyword argument 'det_db_box_thresh'")
                elif call_count == 3:
                    raise TypeError("unexpected keyword argument 'det_db_unclip_ratio'")
                elif call_count == 4:
                    raise TypeError("unexpected keyword argument 'rec_thresh'")
                elif call_count == 5:
                    raise TypeError("unexpected keyword argument 'enable_mkldnn'")
                elif call_count == 6:
                    raise TypeError("unexpected keyword argument 'use_angle_cls'")
                else:
                    return MagicMock()

            MockPaddleOCR.side_effect = side_effect

            # Should not crash
            service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)
            assert service.ocr is not None
            print("✅ Service initialized even after all critical params rejected.")

def test_no_paddleocr_available():
    """Test that when PaddleOCR is not installed, OCR is None."""
    with patch('src.services.mask_service.PADDLE_AVAILABLE', False):
        from src.services.mask_service import MaskGeneratorService
        service = MaskGeneratorService()
        assert service.ocr is None
        print("✅ Handles missing PaddleOCR gracefully.")

def main():
    logging.basicConfig(level=logging.WARNING)  # suppress logs during test
    print("Running auto-healing OCR initialization tests...")
    try:
        test_no_paddleocr_available()
        test_auto_healing_with_rejected_use_gpu()
        test_all_critical_params_rejected_fallback()
        print("\n🎉 All tests passed. Auto-healing initialization is robust.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
