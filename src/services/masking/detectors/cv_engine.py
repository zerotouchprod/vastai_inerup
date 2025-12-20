import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    BERSERK MODE CV Engine.
    Combines 3 dumb detectors:
    1. Low-Threshold Sobel (Edges)
    2. Brightness/Color Threshold (White/Yellow blobs)
    3. Canny Edge Detection

    Goal: Detect ANYTHING that looks like text, ignoring false positives.
    """

    def __init__(self, mask_dilation: int = 15):
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (Berserk Mode, dilation={mask_dilation})")

    def detect(self, image: np.ndarray) -> np.ndarray:
        try:
            # 1. Sobel Detection (Low Threshold)
            mask_sobel = self._run_sobel(image)

            # 2. Color Detection (Bright pixels)
            mask_color = self._run_color(image)

            # 3. Combine
            combined = cv2.bitwise_or(mask_sobel, mask_color)

            # 4. Final Safety Dilation
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (self.mask_dilation, self.mask_dilation))
                combined = cv2.dilate(combined, kernel, iterations=1)

            return combined

        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def _run_sobel(self, image: np.ndarray) -> np.ndarray:
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        h, w = gray.shape

        # Gradient X + Y
        grad_x = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
        grad_y = cv2.Sobel(gray, cv2.CV_16S, 0, 1, ksize=3)

        abs_grad_x = cv2.convertScaleAbs(grad_x)
        abs_grad_y = cv2.convertScaleAbs(grad_y)

        grad = cv2.addWeighted(abs_grad_x, 0.5, abs_grad_y, 0.5, 0)

        # LOW THRESHOLD (20 instead of 50)
        _, binary = cv2.threshold(grad, 20, 255, cv2.THRESH_BINARY)

        # Smear horizontally to connect letters
        # Kernel width = 3% of screen width
        k_w = int(w * 0.03)
        if k_w < 15: k_w = 15

        morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_w, 4))
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, morph_kernel)

        # Filter (Relaxed constraints)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask = np.zeros_like(gray)

        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            ar = cw / float(ch) if ch > 0 else 0

            # Ловим всё, что шире своей высоты (AR > 1.5) и не микроскопическое
            if ar > 1.5 and cw > 15 and ch > 6:
                cv2.rectangle(mask, (x, y), (x + cw, y + ch), 255, -1)

        return mask

    def _run_color(self, image: np.ndarray) -> np.ndarray:
        """Finds bright White and Yellow pixels."""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # White
        lower_white = np.array([0, 0, 180])  # Lower saturation, High Value
        upper_white = np.array([180, 60, 255])
        mask_w = cv2.inRange(hsv, lower_white, upper_white)

        # Yellow
        lower_yellow = np.array([15, 70, 70])
        upper_yellow = np.array([35, 255, 255])
        mask_y = cv2.inRange(hsv, lower_yellow, upper_yellow)

        combined = cv2.bitwise_or(mask_w, mask_y)

        # Filter noise (Open)
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        clean = cv2.morphologyEx(combined, cv2.MORPH_OPEN, k)

        # Dilate to make blobs
        dilate_k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        return cv2.dilate(clean, dilate_k, iterations=2)

    def is_available(self) -> bool:
        return True