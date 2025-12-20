"""
Thread-safe wrapper for PaddleOCR with batch processing support.
"""

import logging
import threading
import concurrent.futures
from typing import List, Optional
from pathlib import Path

import cv2
import numpy as np

from src.core.exceptions import OCRInitializationError

logger = logging.getLogger(__name__)


class ThreadSafeOCR:
    """Thread-safe wrapper for PaddleOCR with batch processing."""
    
    def __init__(self, lang: str = 'en', use_gpu_for_ocr: bool = False, use_angle_cls: bool = False):
        """
        Initialize thread-safe OCR wrapper.
        
        Args:
            lang: Language for OCR
            use_gpu_for_ocr: Use GPU for OCR if available
            use_angle_cls: Use angle classification
        """
        self.lang = lang
        self.use_gpu_for_ocr = use_gpu_for_ocr
        self.use_angle_cls = use_angle_cls
        
        # Thread-local storage for OCR instances
        self._thread_local = threading.local()
        
        # Configure PaddleOCR logging
        self._setup_paddle_logging()
        
        logger.info(f"Initialized ThreadSafeOCR (lang={lang}, use_gpu={use_gpu_for_ocr})")
    
    def _setup_paddle_logging(self) -> None:
        """Configure PaddleOCR logging to reduce noise but keep important info."""
        import warnings
        warnings.filterwarnings('ignore')
        
        # Configure PaddleOCR loggers - set to INFO to see initialization messages
        for logger_name in ['ppocr', 'paddleocr']:
            logging.getLogger(logger_name).setLevel(logging.INFO)
        
        # Suppress more verbose Paddle loggers
        for logger_name in ['paddle', 'paddlex', 'paddle.nn', 'paddle.fluid']:
            logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    def _get_ocr_instance(self):
        """Get OCR instance for current thread."""
        if not hasattr(self._thread_local, "ocr"):
            try:
                from paddleocr import PaddleOCR
                
                # Initialize with optimized settings
                # Note: 'use_gpu' parameter is not supported in current PaddleOCR version
                # Based on error, we should not include it at all
                ocr_params = {
                    'lang': self.lang,
                    'use_textline_orientation': self.use_angle_cls,
                    'det_model_dir': None,   # Use default mobile model (deprecated but still works)
                    'rec_model_dir': None,   # Use default mobile model (deprecated)
                    'cls_model_dir': None,   # No classification model (deprecated)
                    # AGGRESSIVE DETECTION TUNING (using new parameter names)
                    'text_det_thresh': 0.1,          # Lower binarization threshold (default 0.3)
                    'text_det_box_thresh': 0.2,      # Lower box threshold (default 0.6)
                    'text_det_unclip_ratio': 2.0,    # Expand detection boxes (default 1.5)
                    'text_det_limit_side_len': 960,  # Increase side length limit
                    'text_det_limit_type': 'max',    # Limit by max side
                    'text_rec_score_thresh': 0.1,    # Keep recognition result even if confidence low (default 0.5)
                }
                
                # Do NOT add 'use_gpu' or 'gpu' parameters as they cause errors
                # Current PaddleOCR version doesn't support these parameters
                # GPU/CPU selection is handled automatically by PaddlePaddle
                # PaddleOCR will use GPU if PaddlePaddle was compiled with CUDA support
                if self.use_gpu_for_ocr:
                    logger.info("GPU requested for OCR - PaddleOCR will use GPU if available")
                else:
                    logger.info("CPU requested for OCR - PaddleOCR will use CPU")
                
                # Temporarily increase log level to suppress initialization messages
                original_level = logging.getLogger('ppocr').level
                logging.getLogger('ppocr').setLevel(logging.ERROR)
                
                try:
                    self._thread_local.ocr = PaddleOCR(**ocr_params)
                    logger.debug(f"Created PaddleOCR instance for thread {threading.get_ident()}")
                finally:
                    # Restore original log level
                    logging.getLogger('ppocr').setLevel(original_level)
                
                # Additional Paddle configuration
                try:
                    import paddle
                    if hasattr(paddle, 'set_log_level'):
                        paddle.set_log_level(3)  # 0=DEBUG, 1=INFO, 2=WARNING, 3=ERROR, 4=CRITICAL
                    else:
                        logging.getLogger('paddle').setLevel(logging.WARNING)
                except ImportError:
                    pass
                
                # Disable progress bars and other outputs
                import os
                os.environ['PADDLEOCR_LOG_LEVEL'] = '3'
                os.environ['LOG_LEVEL'] = '3'
                
            except ImportError as e:
                raise OCRInitializationError(f"PaddleOCR not installed: {e}")
            except Exception as e:
                raise OCRInitializationError(f"Failed to initialize PaddleOCR: {e}")
        
        return self._thread_local.ocr
    
    def process_batch(self, images: List[np.ndarray], confidence_threshold: float = 0.3) -> List[np.ndarray]:
        """
        Process batch of images and return masks.
        
        Args:
            images: List of numpy arrays (BGR images)
            confidence_threshold: Confidence threshold for text detection
            
        Returns:
            List of mask arrays (uint8, same dimensions as input images)
        """
        if not images:
            return []
        
        # Optimize: reduce resolution for OCR if images are large
        max_ocr_dim = 960  # Increased for better detection of small text
        
        # Prepare images for OCR
        ocr_images = []
        scale_factors = []
        original_shapes = []
        
        for img in images:
            h, w = img.shape[:2]
            original_shapes.append((h, w))
            
            # If image is too large, resize it for OCR
            if max(h, w) > max_ocr_dim:
                scale = max_ocr_dim / max(h, w)
                new_h, new_w = int(h * scale), int(w * scale)
                resized = cv2.resize(img, (new_w, new_h))
                ocr_images.append(resized)
                scale_factors.append(scale)
            else:
                ocr_images.append(img)
                scale_factors.append(1.0)
        
        # Process images in parallel
        masks = [np.zeros((h, w), dtype=np.uint8) for h, w in original_shapes]
        
        def process_single_image(args):
            """Process single image in thread."""
            i, ocr_img, scale_factor, orig_h, orig_w = args
            
            mask = np.zeros((orig_h, orig_w), dtype=np.uint8)
            ocr = self._get_ocr_instance()
            
            # Helper to run OCR on an image
            def run_ocr(img):
                if hasattr(ocr, 'predict'):
                    return ocr.predict(img)
                else:
                    return ocr.ocr(img)
            
            # Perform OCR with preprocessing
            try:
                # Apply CLAHE contrast enhancement
                gray = cv2.cvtColor(ocr_img, cv2.COLOR_BGR2GRAY)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                enhanced = clahe.apply(gray)
                enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
                
                result = run_ocr(enhanced_bgr)
                
                # If no detections, try inverted image
                if not result or (isinstance(result, list) and not result[0]):
                    inverted = cv2.bitwise_not(enhanced_bgr)
                    result = run_ocr(inverted)
                
                if result and result[0] is not None:
                    ocr_result = result[0]
                    self._process_ocr_result(ocr_result, mask, scale_factor, confidence_threshold)
                    
            except Exception as e:
                logger.warning(f"OCR failed for image {i}: {e}")
            
            return i, mask
        
        # Prepare arguments
        args_list = []
        for i, (ocr_img, scale_factor, (orig_h, orig_w)) in enumerate(
                zip(ocr_images, scale_factors, original_shapes)):
            args_list.append((i, ocr_img, scale_factor, orig_h, orig_w))
        
        # Process sequentially to save memory (no parallel processing)
        # This is slower but uses much less memory
        for args in args_list:
            i, mask = process_single_image(args)
            masks[i] = mask
        
        return masks
    
    def _process_ocr_result(self, ocr_result, mask: np.ndarray, scale_factor: float, confidence_threshold: float) -> None:
        """Process OCR result and fill mask."""
        scale_inv = 1.0 / scale_factor if scale_factor != 1.0 else 1.0
        
        # Handle new PaddleOCR result structure (dictionary)
        if isinstance(ocr_result, dict):
            if 'rec_polys' in ocr_result and 'rec_scores' in ocr_result:
                polygons = ocr_result['rec_polys']
                scores = ocr_result['rec_scores']
                
                for poly, score in zip(polygons, scores):
                    try:
                        conf = float(score)
                        if conf > confidence_threshold:
                            # Scale coordinates back to original size
                            scaled_poly = poly * scale_inv
                            pts = scaled_poly.astype(np.int32).reshape((-1, 1, 2))
                            cv2.fillPoly(mask, [pts], 255)
                    except (ValueError, TypeError) as e:
                        logger.debug(f"Failed to parse polygon or score: {e}")
                        continue
            else:
                logger.warning(f"Unexpected OCR result structure: {list(ocr_result.keys())}")
        
        # Handle old structure (list of [[coordinates], (text, confidence)])
        else:
            for line in ocr_result:
                try:
                    coords = line[0]
                    
                    # Extract confidence
                    conf = 0.0
                    if len(line) > 1:
                        second_item = line[1]
                        if isinstance(second_item, (list, tuple)) and len(second_item) > 1:
                            conf = float(second_item[1])
                        elif hasattr(second_item, '__getitem__'):
                            try:
                                conf = float(second_item[1])
                            except (IndexError, TypeError, ValueError):
                                pass
                    
                    if conf > confidence_threshold:
                        # Scale coordinates
                        scaled_coords = [(int(x * scale_inv), int(y * scale_inv)) for x, y in coords]
                        pts = np.array(scaled_coords, dtype=np.int32).reshape((-1, 1, 2))
                        cv2.fillPoly(mask, [pts], 255)
                        
                except (IndexError, TypeError, ValueError) as e:
                    logger.debug(f"Failed to parse OCR result line: {e}")
                    continue
    
    def create_masks_for_directory(self, input_dir: Path, output_dir: Path, 
                                   batch_size: int = 8, confidence_threshold: float = 0.3) -> Path:
        """
        Create masks for all frames in directory.
        
        Args:
            input_dir: Directory with input frames
            output_dir: Directory to save masks
            batch_size: Batch size for processing
            confidence_threshold: Confidence threshold for text detection
            
        Returns:
            Path to directory with masks
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get all frame files
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            raise ValueError(f"No frames found in directory: {input_dir}")
        
        logger.info(f"Generating masks for {len(frames)} frames (batch size: {batch_size})...")
        
        # Process in batches
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i + batch_size]
            
            # Load images
            images = []
            valid_paths = []
            
            for img_path in batch:
                img = cv2.imread(str(img_path))
                if img is not None:
                    images.append(img)
                    valid_paths.append(img_path)
            
            if not images:
                continue
            
            # Process batch
            masks = self.process_batch(images, confidence_threshold)
            
            # Save masks
            for img_path, mask in zip(valid_paths, masks):
                mask_path = output_dir / img_path.name
                cv2.imwrite(str(mask_path), mask)
            
            # Log progress
            processed = min(i + batch_size, len(frames))
            if (i + batch_size) % (batch_size * 5) == 0 or processed == len(frames):
                logger.info(f"Created masks for {processed}/{len(frames)} frames")
        
        return output_dir
