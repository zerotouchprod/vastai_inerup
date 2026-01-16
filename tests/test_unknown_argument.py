import sys
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_unknown_argument_use_gpu():
    """Test that the regex pattern 'Unknown argument: use_gpu' is caught and parameter removed."""
    from src.services.mask_service import MaskGeneratorService

    with patch('src.services.mask_service.PADDLE_AVAILABLE', True):
        with patch('src.services.mask_service.PaddleOCR') as MockPaddleOCR:
            # Simulate the exact error message from logs
            MockPaddleOCR.side_effect = [
                Exception("Unknown argument: use_gpu"),
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
            critical_params = ['det_db_thresh', 'det_db_box_thresh', 'det_db_unclip_ratio', 'rec_thresh']
            for param in critical_params:
                assert param in second_kwargs, f"Critical param {param} missing after retry"

            print("✅ Auto-healing works for 'Unknown argument: use_gpu'.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    try:
        test_unknown_argument_use_gpu()
        print("\n🎉 Test passed.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
