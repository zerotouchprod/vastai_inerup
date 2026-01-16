"""
Pytest configuration for detection component tests.
Mocks OpenCV and other heavy dependencies.
"""

import sys
from unittest.mock import Mock, MagicMock

# Mock OpenCV before any imports
cv2_mock = Mock()
cv2_mock.__version__ = '4.8.0'
cv2_mock.imread = Mock()
cv2_mock.imwrite = Mock()
cv2_mock.cvtColor = Mock()
cv2_mock.fillPoly = Mock()
cv2_mock.Sobel = Mock()
cv2_mock.MSER_create = Mock()
cv2_mock.inpaint = Mock()
cv2_mock.dilate = Mock()
cv2_mock.GaussianBlur = Mock()
cv2_mock.threshold = Mock()
cv2_mock.THRESH_BINARY = 0
cv2_mock.THRESH_OTSU = 8
cv2_mock.COLOR_BGR2GRAY = 6
cv2_mock.COLOR_GRAY2BGR = 8
cv2_mock.IMREAD_COLOR = 1
cv2_mock.INPAINT_TELEA = 0
cv2_mock.INPAINT_NS = 1

sys.modules['cv2'] = cv2_mock

# Mock paddle if needed
paddle_mock = Mock()
paddle_mock.get_log_level = Mock(return_value=2)
paddle_mock.set_log_level = Mock()
sys.modules['paddle'] = paddle_mock

# Mock paddleocr module (but don't mock PaddleOCR class to allow patching)
paddleocr_mock = Mock()
sys.modules['paddleocr'] = paddleocr_mock

# Mock psutil
psutil_mock = Mock()
sys.modules['psutil'] = psutil_mock

# Mock PIL
PIL_mock = Mock()
sys.modules['PIL'] = PIL_mock
