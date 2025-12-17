import logging
import cv2
import numpy as np
from typing import List, Tuple, Optional
from pathlib import Path
# Try-except import to allow running even if paddle is missing (optional safety)
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

# Настройка логирования Paddle, чтобы не спамил в консоль
if PaddleOCR:
    logging.getLogger("ppocr").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


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
        try:
            self.ocr = PaddleOCR(**ocr_params)
            logger.info("PaddleOCR initialized with mobile models (optimized for memory)")
        except Exception as e:
            logger.warning(f"Failed to initialize with mobile models: {e}. Falling back to default.")
            self.ocr = PaddleOCR(lang=lang)
            logger.info("PaddleOCR initialized with default settings")
        
        # Monitor memory usage
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        logger.info(f"Initial memory usage: {memory_mb:.1f} MB")

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
        
        # Process in smaller batches to reduce memory pressure
        batch_size = 4  # Reduced from processing all at once
        processed = 0
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch_frames = frames[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//batch_size + 1}/{(total + batch_size - 1)//batch_size} "
                       f"({len(batch_frames)} frames)...")
            
            for idx, frame_path in enumerate(batch_frames):
                try:
                    self._process_single_frame(frame_path, output_dir / frame_path.name)
                    processed += 1
                    
                    # Show progress
                    if total <= 10:
                        logger.info(f"Processed {processed}/{total} frames: {frame_path.name}")
                    elif processed % 5 == 0 or processed == total:
                        # Monitor memory every 5 frames
                        process = psutil.Process()
                        memory_mb = process.memory_info().rss / 1024 / 1024
                        logger.info(f"Processed {processed}/{total} frames... Memory: {memory_mb:.1f} MB")
                        
                except Exception as e:
                    logger.error(f"Failed to process frame {frame_path}: {e}")
                    # В случае ошибки просто копируем оригинал, чтобы не ломать видео
                    import shutil
                    shutil.copy(frame_path, output_dir / frame_path.name)
                    processed += 1
            
            # Force garbage collection between batches
            gc.collect()
            
            # Check memory usage between batches
            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024
            logger.info(f"Batch completed. Memory usage: {memory_mb:.1f} MB")
            
            # If memory is getting too high, warn user
            if memory_mb > 4000:  # 4GB threshold
                logger.warning(f"High memory usage detected: {memory_mb:.1f} MB. Consider reducing batch size.")

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
