#!/usr/bin/env python3
"""
Unit test that mocks PaddleOCR to verify forced parameters are passed.
"""

import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

class TestMaskServiceForcedParams(unittest.TestCase):
    """Test that MaskGeneratorService passes forced parameters."""

    @patch('src.services.mask_service.PADDLE_AVAILABLE', True)
    @patch('src.services.mask_service.PaddleOCR')
    def test_forced_parameters_passed(self, mock_paddle_ocr):
        """Check that the forced config is passed to PaddleOCR."""
        from src.services.mask_service import MaskGeneratorService

        # Mock the PaddleOCR instance
        mock_instance = MagicMock()
        mock_paddle_ocr.return_value = mock_instance

        # Instantiate service
        service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)

        # Ensure PaddleOCR was called
        self.assertTrue(mock_paddle_ocr.called, "PaddleOCR not initialized")

        # Get the call arguments
        call_args, call_kwargs = mock_paddle_ocr.call_args
        print("PaddleOCR called with kwargs:", call_kwargs)

        # Expected forced parameters
        expected = {
            "use_angle_cls": True,
            "lang": "en",
            "use_gpu": False,
            "show_log": False,
            "enable_mkldnn": True,
            "det_db_thresh": 0.3,
            "det_db_box_thresh": 0.6,
            "det_db_unclip_ratio": 1.5,
            "rec_thresh": 0.6,
        }

        # Check each expected parameter
        for key, expected_value in expected.items():
            self.assertIn(key, call_kwargs, f"Missing parameter: {key}")
            self.assertEqual(call_kwargs[key], expected_value,
                             f"Parameter {key} mismatch: {call_kwargs[key]} != {expected_value}")

        # Ensure no inspect-based filtering occurred (i.e., all parameters present)
        # The inspect module should not be used, but we can't directly test that.
        # Instead we can verify that the call_kwargs length is at least the expected length.
        self.assertGreaterEqual(len(call_kwargs), len(expected),
                                "Some parameters were filtered out")

        print("✅ All forced parameters passed correctly.")

    @patch('src.services.mask_service.PADDLE_AVAILABLE', True)
    @patch('src.services.mask_service.PaddleOCR')
    def test_fallback_on_typeerror(self, mock_paddle_ocr):
        """Test that if TypeError occurs, fallback config is used."""
        from src.services.mask_service import MaskGeneratorService

        # Make PaddleOCR raise TypeError on first call, succeed on second
        mock_paddle_ocr.side_effect = [
            TypeError("unexpected keyword argument"),
            MagicMock()  # fallback call
        ]

        service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)

        # Should have been called twice
        self.assertEqual(mock_paddle_ocr.call_count, 2, "Expected two calls due to fallback")

        # First call should have full forced config
        first_kwargs = mock_paddle_ocr.call_args_list[0][1]
        self.assertIn('det_db_thresh', first_kwargs, "First call missing forced param")

        # Second call should have minimal config (no forced params)
        second_kwargs = mock_paddle_ocr.call_args_list[1][1]
        self.assertNotIn('det_db_thresh', second_kwargs, "Second call should not have forced param")
        self.assertIn('lang', second_kwargs)
        self.assertIn('use_gpu', second_kwargs)

        print("✅ Fallback behavior works as expected.")

if __name__ == '__main__':
    unittest.main(verbosity=2)
