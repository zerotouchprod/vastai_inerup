import sys
import unittest.mock as mock
sys.modules['paddleocr'] = mock.MagicMock()
from src.services.mask_service import MaskGeneratorService

# Mock PaddleOCR class
with mock.patch('src.services.mask_service.PaddleOCR') as MockPaddleOCR:
    instance = mock.MagicMock()
    MockPaddleOCR.return_value = instance
    service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)
    assert MockPaddleOCR.called
    kwargs = MockPaddleOCR.call_args[1]
    print("PaddleOCR called with kwargs:", kwargs)
    expected_keys = {'det_db_thresh', 'det_db_box_thresh', 'det_db_unclip_ratio', 'rec_thresh', 'use_angle_cls', 'lang', 'use_gpu', 'show_log', 'enable_mkldnn'}
    for key in expected_keys:
        assert key in kwargs, f"Missing {key}"
    print("All forced parameters present.")
    print("SUCCESS")
