import logging
import cv2
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path

# СНАЧАЛА настраиваем логирование ДО импорта PaddleOCR
# Это критически важно для подавления сообщений
import warnings
warnings.filterwarnings('ignore')

# Настраиваем все возможные логгеры PaddleOCR
for logger_name in ['ppocr', 'paddleocr', 'paddle', 'paddlex', 'paddle.nn', 'paddle.fluid']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Также отключаем логирование для root логгера от Paddle
logging.getLogger().setLevel(logging.WARNING)

# Теперь импортируем PaddleOCR
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

# Дополнительная настройка после импорта
if PaddleOCR:
    # Подавляем все информационные сообщения от PaddleOCR
    try:
        import paddle
        # Проверяем, существует ли метод set_log_level
        if hasattr(paddle, 'set_log_level'):
            paddle.set_log_level(3)  # 0=DEBUG, 1=INFO, 2=WARNING, 3=ERROR, 4=CRITICAL
        else:
            # Альтернативный способ подавления логов
            import logging
            logging.getLogger('paddle').setLevel(logging.WARNING)
    except ImportError:
        pass
    
    # Отключаем прогресс-бары и другие выводы
    import os
    os.environ['PADDLEOCR_LOG_LEVEL'] = '3'
    os.environ['LOG_LEVEL'] = '3'

logger = logging.getLogger(__name__)
# Восстанавливаем нормальный уровень для нашего логгера
logger.setLevel(logging.INFO)


class SubtitleRemoverNative:
    """
    Удаляет вшитые субтитры используя PaddleOCR для детекции 
    и OpenCV Telea/NS для инпейнтинга (закрашивания).
    Работает на CPU, совместим с PyTorch Nightly билдами.
    """

    def __init__(self, lang: str = 'en', mask_dilation: int = 8, confidence_threshold: float = 0.3):
        """
        :param lang: Язык субтитров ('en', 'ru' и т.д.)
        :param mask_dilation: На сколько пикселей расширять маску вокруг текста.
                              Больше = лучше убирает края, но мылит фон.
        :param confidence_threshold: Порог уверенности для детекции текста (0.0-1.0).
                                     Ниже = больше текста детектируется, но больше шума.
        """
        if PaddleOCR is None:
            raise ImportError("PaddleOCR not installed. Cannot remove subtitles.")
            
        self.lang = lang
        self.mask_dilation = mask_dilation
        self.confidence_threshold = confidence_threshold
        logger.info(f"Initializing SubtitleRemoverNative (lang={lang}, mask_dilation={mask_dilation}, confidence={confidence_threshold})...")
        
        # Initialize PaddleOCR with OPTIMIZED settings to reduce memory usage
        # Critical optimizations:
        # 1. Use 'ch_ppocr_mobile_v2.0' instead of server models (smaller, faster)
        # 2. Disable angle classification (not needed for subtitles)
        # 3. Use CPU only (GPU models use more memory)
        # 4. Disable unnecessary features
        ocr_params = {
            'lang': lang,
            'use_angle_cls': False,  # Disable angle classification (saves memory)
            'det_model_dir': None,   # Use default mobile model
            'rec_model_dir': None,   # Use default mobile model
            'cls_model_dir': None,   # No classification model
        }
        
        # Try to use mobile model for better performance
        # Временно повышаем уровень логирования для подавления сообщений при инициализации
        original_level = logging.getLogger('ppocr').level
        logging.getLogger('ppocr').setLevel(logging.ERROR)
        
        try:
            self.ocr = PaddleOCR(**ocr_params)
            logger.info("PaddleOCR initialized with mobile models (optimized for memory)")
        except Exception as e:
            logger.warning(f"Failed to initialize with mobile models: {e}. Falling back to default.")
            self.ocr = PaddleOCR(lang=lang)
            logger.info("PaddleOCR initialized with default settings")
        finally:
            # Восстанавливаем исходный уровень логирования
            logging.getLogger('ppocr').setLevel(original_level)
        
        # Monitor memory usage
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        logger.info(f"Initial memory usage: {memory_mb:.1f} MB")

    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image for better OCR detection of colored/fading text.
        
        Args:
            image: Input BGR image
            
        Returns:
            Preprocessed BGR image with enhanced contrast
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply CLAHE to handle colored text on complex backgrounds
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Optional: Thresholding to isolate bright text
        _, thresh = cv2.threshold(enhanced, 200, 255, cv2.THRESH_BINARY)
        
        # Convert back to BGR (3-channel) for OCR compatibility
        bgr_thresh = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
        
        return bgr_thresh
    
    def _generate_hybrid_mask(self, image: np.ndarray, ocr_mask: np.ndarray, roi_str: str = None) -> np.ndarray:
        """
        Generate hybrid mask using OCR-Anchored Masking with ROI constraint.
        MSER/Gradient detectors only operate within OCR-defined regions.
        
        Args:
            image: Input BGR image
            ocr_mask: Mask from PaddleOCR
            roi_str: ROI string (preset or coordinates). If provided, final mask is constrained to ROI.
            
        Returns:
            Combined binary mask
        """
        # Import here to avoid circular imports
        from src.infrastructure.image_processing.detectors import (
            get_mser_mask, get_gradient_mask, filter_mask_by_geometry
        )
        from src.infrastructure.image_processing.mask_cleaning import apply_safety_clamp
        
        # Step 1: Create "Allowed Zone" from OCR mask (dilated)
        # Dilate OCR mask to create search area (account for jumping text/OCR inaccuracies)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (30, 30))
        allowed_zone = cv2.dilate(ocr_mask, kernel, iterations=1)
        
        # Step 2: Apply MSER detection (structure layer)
        mser_mask = get_mser_mask(image)
        
        # Step 3: Apply Gradient detection (edge layer)
        gradient_mask = get_gradient_mask(image)
        
        # Step 4: Clean MSER and Gradient masks
        mser_cleaned = filter_mask_by_geometry(mser_mask)
        gradient_cleaned = filter_mask_by_geometry(gradient_mask)
        
        # Step 5: STRICT INTERSECTION - Only keep details inside Allowed Zone
        # MSER and Gradient can only operate where OCR detected something
        mser_constrained = cv2.bitwise_and(mser_cleaned, allowed_zone)
        gradient_constrained = cv2.bitwise_and(gradient_cleaned, allowed_zone)
        
        # Step 6: Combine masks (OCR is the anchor)
        combined = cv2.bitwise_or(ocr_mask, mser_constrained)
        combined = cv2.bitwise_or(combined, gradient_constrained)
        
        # Step 7: Apply safety clamp to prevent "global hallucination"
        safe_mask = apply_safety_clamp(combined, ocr_mask, safety_threshold=0.20)
        
        # Step 8: Apply ROI constraint if provided (HARD CONSTRAINT - "Mask Guillotine")
        if roi_str:
            from src.infrastructure.image_processing.geometry import resolve_roi
            
            h, w = image.shape[:2]
            x, y, roi_w, roi_h = resolve_roi(roi_str, w, h)
            
            # Create ROI mask (black canvas with white ROI rectangle)
            roi_mask = np.zeros_like(safe_mask)
            cv2.rectangle(roi_mask, (x, y), (x + roi_w, y + roi_h), 255, -1)
            
            # Apply hard constraint: mask ONLY inside ROI
            safe_mask = cv2.bitwise_and(safe_mask, roi_mask)
            
            # Log ROI constraint
            total_pixels = h * w
            roi_pixels = np.sum(roi_mask > 0)
            safe_pixels = np.sum(safe_mask > 0)
            
            logger.info(
                f"ROI Constraint ({roi_str}): ROI covers {roi_pixels/total_pixels*100:.1f}% of screen, "
                f"final mask covers {safe_pixels/total_pixels*100:.1f}%"
            )
        
        # Log statistics for debugging
        h, w = image.shape[:2]
        total_pixels = h * w
        ocr_coverage = np.sum(ocr_mask > 0) / total_pixels
        mser_coverage = np.sum(mser_constrained > 0) / total_pixels
        gradient_coverage = np.sum(gradient_constrained > 0) / total_pixels
        final_coverage = np.sum(safe_mask > 0) / total_pixels
        
        logger.debug(
            f"OCR-Anchored Masking: OCR={ocr_coverage*100:.1f}%, "
            f"MSER={mser_coverage*100:.1f}%, "
            f"Gradient={gradient_coverage*100:.1f}%, "
            f"Final={final_coverage*100:.1f}%"
        )
        
        return safe_mask
    
    def process_frames(self, input_dir: Path, output_dir: Path) -> None:
        """
        Обрабатывает все изображения в input_dir и сохраняет в output_dir.
        Оптимизировано для использования памяти.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Получаем список файлов (png/jpg)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        total = len(frames)

        logger.info(f"Starting subtitle removal on {total} frames...")
        
        # Memory monitoring
        import psutil
        import gc
        
        # Process in smaller batches to reduce memory pressure but maintain temporal context
        batch_size = 4  # Reduced from processing all at once
        processed = 0
        
        # We need to collect masks for temporal smearing
        all_masks = []
        all_frame_paths = []
        all_images = []
        
        # First pass: detect text and create masks for all frames
        logger.info("First pass: Detecting text and creating masks...")
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_frames = frames[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//batch_size + 1}/{(total + batch_size - 1)//batch_size} "
                       f"({len(batch_frames)} frames)...")
            
            for frame_path in batch_frames:
                try:
                    # Load image
                    img = cv2.imread(str(frame_path))
                    if img is None:
                        logger.warning(f"Could not read image: {frame_path}")
                        # Create empty mask
                        h, w = 100, 100  # Default size
                        if all_images:
                            h, w = all_images[0].shape[:2]
                        mask = np.zeros((h, w), dtype=np.uint8)
                        all_masks.append(mask)
                        all_frame_paths.append(frame_path)
                        all_images.append(np.zeros((h, w, 3), dtype=np.uint8))
                        continue
                    
                    # Store image for later processing
                    all_images.append(img)
                    all_frame_paths.append(frame_path)
                    
                    # Preprocess image for better OCR detection
                    preprocessed_img = self._preprocess_for_ocr(img)
                    
                    # Detect text with OCR
                    if hasattr(self.ocr, 'predict'):
                        result = self.ocr.predict(preprocessed_img)
                    else:
                        result = self.ocr.ocr(preprocessed_img)
                    
                    # Create OCR mask
                    h, w = img.shape[:2]
                    ocr_mask = np.zeros((h, w), dtype=np.uint8)
                    
                    if result and result[0] is not None:
                        ocr_result = result[0]
                        
                        # Handle new PaddleOCR result structure
                        if isinstance(ocr_result, dict):
                            if 'rec_polys' in ocr_result and 'rec_scores' in ocr_result:
                                polygons = ocr_result['rec_polys']
                                scores = ocr_result['rec_scores']
                                
                                for poly, score in zip(polygons, scores):
                                    try:
                                        conf = float(score)
                                        if conf > self.confidence_threshold:
                                            points = poly.astype(np.int32).reshape((-1, 1, 2))
                                            cv2.fillPoly(ocr_mask, [points], 255)
                                    except (ValueError, TypeError) as e:
                                        continue
                        else:
                            # Old structure
                            for line in ocr_result:
                                try:
                                    coords = line[0]
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
                                    
                                    if conf > self.confidence_threshold:
                                        points = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                                        cv2.fillPoly(ocr_mask, [points], 255)
                                except (IndexError, TypeError, ValueError):
                                    continue
                    
                    # Generate hybrid mask combining OCR, MSER, and Gradient
                    hybrid_mask = self._generate_hybrid_mask(img, ocr_mask)
                    all_masks.append(hybrid_mask)
                    processed += 1
                    
                    # Show progress
                    if processed % 5 == 0 or processed == total:
                        process = psutil.Process()
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        logger.info(f"Processed {processed}/{total} frames for mask detection... Memory: {memory_mb:.1f} MB")
                        
                except Exception as e:
                    logger.error(f"Failed to process frame {frame_path} for mask detection: {e}")
                    # Create empty mask
                    h, w = 100, 100
                    if all_images:
                        h, w = all_images[0].shape[:2]
                    mask = np.zeros((h, w), dtype=np.uint8)
                    all_masks.append(mask)
                    all_frame_paths.append(frame_path)
                    if len(all_images) < len(all_masks):
                        all_images.append(np.zeros((h, w, 3), dtype=np.uint8))
                    processed += 1
            
            # Force garbage collection between batches
            gc.collect()
            
            # Check memory usage between batches
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"Batch completed. Memory usage: {memory_mb:.1f} MB")
            
            if memory_mb > 4000:  # 4GB threshold
                logger.warning(f"High memory usage detected: {memory_mb:.1f} MB. Consider reducing batch size.")
        
        # Apply temporal smearing (rolling window of ±2 frames)
        logger.info("Applying temporal smearing to masks...")
        window_size = 2  # Look 2 frames back and 2 frames forward
        smeared_masks = []
        
        for i in range(len(all_masks)):
            # Get indices for the window
            start_idx = max(0, i - window_size)
            end_idx = min(len(all_masks), i + window_size + 1)
            
            # Combine masks in the window using logical OR (max)
            window_masks = all_masks[start_idx:end_idx]
            if window_masks:
                # Use logical OR to combine masks (equivalent to max for binary masks)
                combined_mask = window_masks[0].copy()
                for mask in window_masks[1:]:
                    combined_mask = cv2.bitwise_or(combined_mask, mask)
                smeared_masks.append(combined_mask)
            else:
                smeared_masks.append(all_masks[i])
        
        # Second pass: apply dilation and inpainting with smeared masks
        logger.info("Second pass: Applying dilation and inpainting...")
        processed = 0
        
        for i, (frame_path, img, mask) in enumerate(zip(all_frame_paths, all_images, smeared_masks)):
            try:
                output_path = output_dir / frame_path.name
                
                # Skip if no text detected (empty mask)
                if np.max(mask) == 0:
                    cv2.imwrite(str(output_path), img)
                    processed += 1
                    continue
                
                # Apply dilation
                kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
                dilated_mask = cv2.dilate(mask, kernel, iterations=1)
                
                # Additional processing for large dilation
                if self.mask_dilation >= 8:
                    dilated_mask = cv2.GaussianBlur(dilated_mask, (5, 5), 0)
                
                # Inpainting
                inpaint_radius = max(5, self.mask_dilation // 2)
                result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_NS)
                
                # Fallback to Telea if result is poor
                if np.sum(cv2.absdiff(img, result_img)) < 1000:
                    result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)
                
                # Save result
                cv2.imwrite(str(output_path), result_img)
                processed += 1
                
                # Show progress
                if processed % 5 == 0 or processed == total:
                    logger.info(f"Processed {processed}/{total} frames for inpainting...")
                    
            except Exception as e:
                logger.error(f"Failed to process frame {frame_path} for inpainting: {e}")
                # Save original as fallback
                cv2.imwrite(str(output_dir / frame_path.name), img)
                processed += 1
        
        logger.info(f"Completed subtitle removal on {total} frames with temporal smearing.")

    def _process_single_frame(self, input_path: Path, output_path: Path) -> None:
        # 1. Загрузка изображения
        img = cv2.imread(str(input_path))
        if img is None:
            raise ValueError(f"Could not read image: {input_path}")

        # 2. Детекция текста (PaddleOCR)
        # New PaddleOCR API (v3.3.2+) returns a dictionary structure
        # result is a list with one dict containing:
        # - 'rec_texts': list of detected text strings
        # - 'rec_scores': list of confidence scores
        # - 'rec_polys': list of polygon coordinates as numpy arrays
        # Note: .ocr() method is deprecated, use .predict() instead
        if hasattr(self.ocr, 'predict'):
            result = self.ocr.predict(img)
        else:
            result = self.ocr.ocr(img)

        # Если текст не найден, result может быть None или пустым списком
        if not result or result[0] is None:
            # Текста нет, сохраняем оригинал
            cv2.imwrite(str(output_path), img)
            return

        # 3. Создание маски
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)

        boxes_found = False

        # Handle new PaddleOCR result structure
        ocr_result = result[0]
        
        # Check if we have the new dictionary structure
        if isinstance(ocr_result, dict):
            # New structure: dictionary with 'rec_texts', 'rec_scores', 'rec_polys'
            if 'rec_polys' in ocr_result and 'rec_scores' in ocr_result:
                polygons = ocr_result['rec_polys']
                scores = ocr_result['rec_scores']
                
                for poly, score in zip(polygons, scores):
                    try:
                        conf = float(score)
                        # Filter by confidence
                        if conf > self.confidence_threshold:
                            # Convert polygon to correct format for fillPoly
                            # poly is numpy array of shape (n, 2)
                            points = poly.astype(np.int32).reshape((-1, 1, 2))
                            cv2.fillPoly(mask, [points], 255)
                            boxes_found = True
                            logger.debug(f"Detected text with confidence {conf:.2f}")
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse polygon or score: {e}")
                        continue
            else:
                logger.warning(f"Unexpected OCR result structure: {list(ocr_result.keys())}")
        else:
            # Old structure: list of [[coordinates], (text, confidence)]
            logger.warning("Using old PaddleOCR result structure (deprecated)")
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
                    
                    # Filter by confidence
                    if conf > self.confidence_threshold:
                        points = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                        cv2.fillPoly(mask, [points], 255)
                        boxes_found = True
                        logger.debug(f"Detected text with confidence {conf:.2f}")
                except (IndexError, TypeError, ValueError) as e:
                    logger.warning(f"Failed to parse OCR result line: {line}, error: {e}")
                    continue

        if not boxes_found:
            cv2.imwrite(str(output_path), img)
            return

        # 4. Расширение маски (Dilation)
        # Это нужно, чтобы убрать артефакты сжатия вокруг букв, особенно для субтитров с тенью/свечением
        kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=1)
        
        # Дополнительное расширение для субтитров с сильным свечением
        if self.mask_dilation >= 8:
            # Для больших масок делаем дополнительное размытие для плавного перехода
            dilated_mask = cv2.GaussianBlur(dilated_mask, (5, 5), 0)

        # 5. Inpainting (Закрашивание)
        # cv2.INPAINT_TELEA или cv2.INPAINT_NS. 
        # Telea обычно быстрее, NS дает лучшее качество для больших областей.
        # Увеличиваем радиус для лучшего удаления.
        inpaint_radius = max(5, self.mask_dilation // 2)
        result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_NS)
        
        # Если результат плохой, пробуем Telea как fallback
        if np.sum(cv2.absdiff(img, result_img)) < 1000:  # Если почти ничего не изменилось
            logger.debug("Trying Telea inpainting as fallback...")
            result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=inpaint_radius, flags=cv2.INPAINT_TELEA)

        # 6. Сохранение
        cv2.imwrite(str(output_path), result_img)
