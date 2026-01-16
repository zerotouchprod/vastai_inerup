"""
OCR Engine component for text detection using PaddleOCR.
Encapsulates PaddleOCR initialization, logging suppression, and output normalization.
"""

import logging
import warnings
import os
from typing import List, Tuple, Optional
import numpy as np
import cv2

logger = logging.getLogger(__name__)


class OcrEngine:
    """
    OCR Engine that handles PaddleOCR initialization and text detection.
    
    Responsibilities:
    1. Encapsulate PaddleOCR initialization with optimized settings
    2. Suppress logging locally (not globally)
    3. Normalize output format (handling v3 vs v4 API differences)
    4. Provide clean interface for text detection
    """
    
    def __init__(self, config):
        """
        Initialize OCR engine with configuration.
        
        Args:
            config: AppConfig instance containing OCR settings
        """
        self.config = config
        self.lang = config.OCR_LANG
        self.confidence_threshold = config.CONFIDENCE_THRESHOLD
        
        # Store original logging levels
        self._original_log_levels = {}
        
        # Initialize PaddleOCR with logging suppression
        self.ocr = self._initialize_paddleocr()
        
        logger.info(f"OCR Engine initialized (lang={self.lang}, confidence={self.confidence_threshold})")
    
    def _initialize_paddleocr(self):
        """
        Initialize PaddleOCR with optimized settings and local logging suppression.
        
        Returns:
            Initialized PaddleOCR instance
        """
        # Apply local logging suppression before importing PaddleOCR
        self._setup_logging_suppression()
        
        try:
            from paddleocr import PaddleOCR
        except ImportError as e:
            logger.error("PaddleOCR not installed. Please install with: pip install paddlepaddle paddleocr")
            raise ImportError("PaddleOCR not installed. Cannot initialize OCR engine.") from e
        
        # Optimized parameters for subtitle detection
        ocr_params = {
            'lang': self.lang,
            'use_angle_cls': False,  # Disable angle classification (saves memory)
            'det_model_dir': None,   # Use default mobile model
            'rec_model_dir': None,   # Use default mobile model
            'cls_model_dir': None,   # No classification model
            'use_gpu': self.config.USE_GPU_FOR_OCR,
        }
        
        # Try to suppress paddle logging during initialization
        import paddle
        original_log_level = None
        if hasattr(paddle, 'set_log_level'):
            original_log_level = paddle.get_log_level()
            paddle.set_log_level(3)  # ERROR level
        
        try:
            ocr = PaddleOCR(**ocr_params)
            logger.info("PaddleOCR initialized with mobile models (optimized for memory)")
        except Exception as e:
            logger.warning(f"Failed to initialize with mobile models: {e}. Falling back to default.")
            ocr = PaddleOCR(lang=self.lang, use_gpu=self.config.USE_GPU_FOR_OCR)
            logger.info("PaddleOCR initialized with default settings")
        finally:
            # Restore original log level
            if original_log_level is not None:
                paddle.set_log_level(original_log_level)
        
        return ocr
    
    def _setup_logging_suppression(self):
        """
        Setup logging suppression for PaddleOCR components.
        This is done locally using context managers, not globally.
        """
        # List of logger names used by PaddleOCR
        paddle_loggers = ['ppocr', 'paddleocr', 'paddle', 'paddlex', 'paddle.nn', 'paddle.fluid']
        
        for logger_name in paddle_loggers:
            logger_obj = logging.getLogger(logger_name)
            self._original_log_levels[logger_name] = logger_obj.level
            logger_obj.setLevel(logging.WARNING)
        
        # Suppress warnings locally
        warnings.filterwarnings('ignore', category=UserWarning)
        warnings.filterwarnings('ignore', category=FutureWarning)
        
        # Set environment variables to suppress PaddleOCR progress bars
        os.environ['PADDLEOCR_LOG_LEVEL'] = '3'
        os.environ['LOG_LEVEL'] = '3'
    
    def detect_text(self, image: np.ndarray) -> List[Tuple[np.ndarray, float]]:
        """
        Detect text in image and return polygons with confidence scores.
        
        Args:
            image: Input BGR image as numpy array
            
        Returns:
            List of tuples (polygon, confidence_score) where:
            - polygon: numpy array of shape (n, 2) with polygon coordinates
            - confidence_score: float between 0.0 and 1.0
        """
        if image is None or image.size == 0:
            logger.warning("Empty image provided to OCR engine")
            return []
        
        # Ensure image is in correct format
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 1:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        
        # Perform OCR detection
        try:
            # Use appropriate method based on PaddleOCR version
            if hasattr(self.ocr, 'predict'):
                result = self.ocr.predict(image)
            else:
                result = self.ocr.ocr(image)
        except Exception as e:
            logger.error(f"OCR detection failed: {e}")
            return []
        
        # Normalize result format
        polygons_with_scores = self._normalize_ocr_result(result)
        
        # Filter by confidence threshold
        filtered_results = [
            (poly, score) for poly, score in polygons_with_scores 
            if score >= self.confidence_threshold
        ]
        
        logger.debug(f"Detected {len(filtered_results)} text regions with confidence >= {self.confidence_threshold}")
        return filtered_results
    
    def _normalize_ocr_result(self, result) -> List[Tuple[np.ndarray, float]]:
        """
        Normalize OCR result to handle different PaddleOCR API versions.
        
        Args:
            result: Raw OCR result from PaddleOCR
            
        Returns:
            List of tuples (polygon, confidence_score)
        """
        polygons_with_scores = []
        
        if not result or result[0] is None:
            return polygons_with_scores
        
        ocr_result = result[0]
        
        # Handle new PaddleOCR v3/v4 dictionary structure
        if isinstance(ocr_result, dict):
            if 'rec_polys' in ocr_result and 'rec_scores' in ocr_result:
                polygons = ocr_result['rec_polys']
                scores = ocr_result['rec_scores']
                
                for poly, score in zip(polygons, scores):
                    try:
                        conf = float(score)
                        # Convert polygon to numpy array if needed
                        if not isinstance(poly, np.ndarray):
                            poly = np.array(poly, dtype=np.float32)
                        polygons_with_scores.append((poly, conf))
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse polygon or score: {e}")
                        continue
            else:
                logger.warning(f"Unexpected OCR result structure: {list(ocr_result.keys())}")
        
        # Handle old PaddleOCR list structure
        else:
            for line in ocr_result:
                try:
                    # First element should always be coordinates
                    coords = line[0]
                    
                    # Second element could be (text, confidence) or [text, confidence]
                    conf = 0.0
                    if len(line) > 1:
                        second_item = line[1]
                        if isinstance(second_item, (list, tuple)) and len(second_item) > 1:
                            # Structure: (text, confidence) or [text, confidence]
                            conf = float(second_item[1])
                        elif hasattr(second_item, '__getitem__'):
                            # Try to get confidence if it's indexable
                            try:
                                conf = float(second_item[1])
                            except (IndexError, TypeError, ValueError):
                                pass
                    
                    # Convert coordinates to numpy array
                    if not isinstance(coords, np.ndarray):
                        poly = np.array(coords, dtype=np.float32)
                    else:
                        poly = coords.astype(np.float32)
                    
                    polygons_with_scores.append((poly, conf))
                except (IndexError, TypeError, ValueError) as e:
                    logger.warning(f"Failed to parse OCR result line: {e}")
                    continue
        
        return polygons_with_scores
    
    def create_mask_from_detection(self, image_shape, polygons_with_scores) -> np.ndarray:
        """
        Create binary mask from detected text polygons.
        
        Args:
            image_shape: Tuple (height, width) of the image
            polygons_with_scores: List of tuples (polygon, confidence_score)
            
        Returns:
            Binary mask with detected text regions filled with 255
        """
        if not polygons_with_scores:
            # Return empty mask
            h, w = image_shape[:2] if len(image_shape) == 3 else image_shape
            return np.zeros((h, w), dtype=np.uint8)
        
        h, w = image_shape[:2] if len(image_shape) == 3 else image_shape
        mask = np.zeros((h, w), dtype=np.uint8)
        
        for polygon, confidence in polygons_with_scores:
            try:
                # Convert polygon to integer coordinates for fillPoly
                points = polygon.astype(np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [points], 255)
            except Exception as e:
                logger.warning(f"Failed to draw polygon on mask: {e}")
                continue
        
        return mask
    
    def cleanup(self):
        """
        Clean up resources and restore original logging levels.
        """
        # Restore original logging levels
        for logger_name, original_level in self._original_log_levels.items():
            logging.getLogger(logger_name).setLevel(original_level)
        
        # Clear environment variables
        if 'PADDLEOCR_LOG_LEVEL' in os.environ:
            del os.environ['PADDLEOCR_LOG_LEVEL']
        if 'LOG_LEVEL' in os.environ:
            del os.environ['LOG_LEVEL']
        
        logger.info("OCR Engine cleanup completed")
