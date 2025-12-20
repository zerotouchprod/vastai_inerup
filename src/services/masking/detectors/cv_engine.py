import logging
import cv2
import numpy as np

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class CVEngine(TextDetector):
    """
    VSR-Inspired CV Engine (Sobel/Raster).
    Uses Sobel Operators to find high-frequency text edges.
    This works regardless of text color (white, yellow, gradient) or borders.
    """
    
    def __init__(self, mask_dilation: int = 15):
        """
        Initialize CV engine.
        Args:
            mask_dilation: Dilation radius for final mask (default: 15)
        """
        self.mask_dilation = mask_dilation
        logger.info(f"CV Engine initialized (VSR-Sobel Mode, dilation={mask_dilation})")
    
    def detect(self, image: np.ndarray) -> np.ndarray:
        """
        Detect text using Sobel Edge Detection and Aggressive Morphology.
        """
        try:
            # 1. Run VSR-style detection
            mask = self._run_sobel_detection(image)
            
            # 2. Apply final user-configured dilation (Safety Buffer)
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(
                    cv2.MORPH_RECT, 
                    (self.mask_dilation, self.mask_dilation)
                )
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            return mask
            
        except Exception as e:
            logger.error(f"CV detection failed: {e}", exc_info=True)
            return np.zeros(image.shape[:2], dtype=np.uint8)

    def _run_sobel_detection(self, image: np.ndarray) -> np.ndarray:
        """
        Core logic adapted from Video-Subtitle-Remover (Raster Detection).
        Finds regions with high density of vertical/horizontal edges.
        """
        # 1. Convert to Gray
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        h, w = gray.shape

        # 2. SOBEL DETECTION
        # Find vertical edges (sides of letters) and horizontal edges
        scale = 1
        delta = 0
        ddepth = cv2.CV_16S

        grad_x = cv2.Sobel(gray, ddepth, 1, 0, ksize=3, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)
        abs_grad_x = cv2.convertScaleAbs(grad_x)

        grad_y = cv2.Sobel(gray, ddepth, 0, 1, ksize=3, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)
        abs_grad_y = cv2.convertScaleAbs(grad_y)

        # Combine gradients (Text has strong edges in all directions)
        grad = cv2.addWeighted(abs_grad_x, 0.5, abs_grad_y, 0.5, 0)

        # 3. Aggressive Thresholding
        # We want only the sharpest edges. 
        # VSR uses a fixed threshold because edges of text are always high contrast relative to themselves.
        _, binary = cv2.threshold(grad, 50, 255, cv2.THRESH_BINARY)

        # 4. EXTREME Morphology (The VSR Secret)
        # Calculate dynamic kernel width based on image size.
        # ~3% of screen width is a good approximation for "sentence gap".
        # For 1920px width -> ~57px kernel.
        kernel_width = int(w * 0.03) 
        if kernel_width < 20: kernel_width = 20
        
        # Wide kernel to connect words, short kernel to keep lines separate
        morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 6))
        
        # Morph Close: Fill gaps inside letters and between words
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, morph_kernel)
        
        # 5. Filtering Contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        mask = np.zeros_like(gray)
        
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            aspect_ratio = cw / float(ch)
            
            # VSR-Lite Logic:
            # 1. Aspect Ratio > 2.0 (Text is long)
            # 2. Not too small (cw > 25, ch > 8)
            # 3. Not the whole screen (cw < 95%, ch < 50%)
            if (aspect_ratio > 2.0 and 
                cw > 25 and ch > 8 and 
                cw < w * 0.95 and ch < h * 0.5):
                
                # Draw the detected block
                cv2.rectangle(mask, (x, y), (x + cw, y + ch), 255, -1)

        return mask
    
    def is_available(self) -> bool:
        return True