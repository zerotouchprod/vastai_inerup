"""
OCR-based text detector using PaddleOCR with auto-healing initialization.
"""

import logging
import re
from typing import List, Dict, Any, Optional
import numpy as np
import cv2

from src.services.masking.interfaces import TextDetector

logger = logging.getLogger(__name__)


class OCREngine(TextDetector):
    """
    Text detector that uses PaddleOCR (AI) for text detection.
    
    Features:
    - Auto-healing initialization: removes unsupported parameters automatically.
    - Version-agnostic result parsing: handles both dict and list result structures.
    - Graceful degradation: if OCR fails to initialize, detector becomes unavailable.
    """
    
    def __init__(self,
                 lang: str = 'en',
                 use_gpu: bool = False,
                 confidence_threshold: float = 0.1):
        """
        Initialize OCR engine.
        
        Args:
            lang: Language for OCR (default: 'en')
            use_gpu: Use GPU for OCR if available
            confidence_threshold: Minimum confidence for text detection (not fully used)
        """
        self.lang = lang
        self.use_gpu = use_gpu
        self.confidence_threshold = confidence_threshold
        self.ocr = None
        
        # Configuration for PaddleOCR (aggressive detection)
        self.config = {
            "use_angle_cls": False,
            "lang": self.lang,
            "enable_mkldnn": True,
            "det_db_thresh": 0.1,
            "det_db_box_thresh": 0.2,
            "det_db_unclip_ratio": 2.0,
        }
        
        self._initialize_ocr()
    
    def _initialize_ocr(self) -> None:
        """Initialize PaddleOCR with auto-healing parameter handling."""
        self.ocr = self._init_ocr_robust(self.config)
        if self.ocr is not None:
            logger.info(f"OCR Engine initialized (lang={self.lang}, GPU={self.use_gpu})")
            # Try to force thresholds (may not work in all versions)
            try:
                self.ocr.det_db_thresh = 0.1
                self.ocr.det_db_box_thresh = 0.2
            except Exception:
                pass
        else:
            logger.warning("OCR Engine failed to initialize. Falling back to CV-only mode.")
    
    def _init_ocr_robust(self, params: Dict[str, Any]) -> Optional[Any]:
        """
        Initialize PaddleOCR with automatic removal of unsupported parameters.
        
        Args:
            params: Dictionary of parameters to pass to PaddleOCR constructor.
            
        Returns:
            PaddleOCR instance or None if initialization fails.
        """
        from paddleocr import PaddleOCR
        
        attempts = 0
        max_attempts = len(params) + 2
        current_params = params.copy()
        
        # Regex patterns to detect unsupported argument errors
        error_patterns = [
            r"unexpected keyword argument ['\"]([^'\"]+)['\"]",
            r"Unknown argument:?\s+([A-Za-z0-9_]+)",
            r"got an unexpected keyword argument ['\"]([^'\"]+)['\"]"
        ]
        
        while attempts < max_attempts:
            try:
                return PaddleOCR(**current_params)
            except Exception as e:
                error_msg = str(e)
                bad_arg = None
                for pattern in error_patterns:
                    match = re.search(pattern, error_msg)
                    if match:
                        bad_arg = match.group(1)
                        break
                
                if bad_arg and bad_arg in current_params:
                    logger.warning(f"PaddleOCR removing unsupported argument: {bad_arg}")
                    del current_params[bad_arg]
                else:
                    logger.error(f"PaddleOCR initialization failed: {e}")
                    return None
            attempts += 1
        return None
    
    def _run_ocr_detection(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Run OCR detection on image and return list of polygon points.
        
        Args:
            image: Input image in BGR format.
            
        Returns:
            List of polygon arrays (each polygon is Nx2 int32 array).
        """
        if self.ocr is None:
            return []
        
        try:
            # Call OCR without extra parameters (default detection + recognition)
            result = self.ocr.ocr(image)
            boxes = []
            
            if isinstance(result, dict):
                # New structure: dict with 'rec_polys' etc.
                if 'rec_polys' in result:
                    polygons = result['rec_polys']
                    for poly in polygons:
                        try:
                            # Ensure polygon is numeric
                            if poly.dtype.kind in 'iuf':  # integer, unsigned, float
                                boxes.append(poly.astype(np.int32))
                            else:
                                # try to convert
                                boxes.append(poly.astype(float).astype(np.int32))
                        except Exception as e:
                            logger.debug(f"Failed to convert polygon {poly}: {e}")
                            continue
                            
            elif isinstance(result, list) and len(result) > 0:
                # Old structure: list of [[coordinates], (text, confidence)]
                ocr_result = result[0]  # first element for the image
                if ocr_result is None:
                    return []
                    
                for line in ocr_result:
                    if len(line) > 0:
                        coords = line[0]  # polygon coordinates
                        # Ensure coords is a list of numeric pairs
                        try:
                            numeric_coords = []
                            for point in coords:
                                if isinstance(point, (list, tuple)) and len(point) >= 2:
                                    x = float(point[0])
                                    y = float(point[1])
                                    numeric_coords.append([int(x), int(y)])
                                else:
                                    # skip malformed point
                                    continue
                            if len(numeric_coords) >= 3:  # need at least triangle
                                boxes.append(np.array(numeric_coords, dtype=np.int32))
                        except (ValueError, TypeError, IndexError) as e:
                            logger.debug(f"Failed to parse coordinates {coords}: {e}")
                            continue
            return boxes
            
        except Exception as e:
            logger.warning(f"OCR detection failed: {e}")
            return []
    
    def detect(self, image: np.ndarray) -> np.ndarray:
        """
        Detect text regions using PaddleOCR.
        
        Args:
            image: Input image in BGR format.
            
        Returns:
            Binary mask where detected text regions are white (255).
        """
        if self.ocr is None:
            # Return empty mask if OCR is not available
            return np.zeros(image.shape[:2], dtype=np.uint8)
        
        h, w = image.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        try:
            # Invert image to help with bright text
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            inverted = cv2.bitwise_not(gray)
            inverted_bgr = cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)
            
            boxes = self._run_ocr_detection(inverted_bgr)
            if boxes:
                for box in boxes:
                    cv2.fillPoly(mask, [box], 255)
                
                # Dilate the mask slightly to ensure full coverage
                dilation_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
                mask = cv2.dilate(mask, dilation_kernel, iterations=1)
                
                logger.debug(f"OCR detected {len(boxes)} text regions")
            else:
                logger.debug("OCR detected 0 text regions")
                
        except Exception as e:
            logger.warning(f"OCR detection step failed: {e}")
        
        return mask
    
    def is_available(self) -> bool:
        """
        Check if OCR engine is available.
        
        Returns:
            True if OCR instance is initialized, False otherwise.
        """
        return self.ocr is not None
