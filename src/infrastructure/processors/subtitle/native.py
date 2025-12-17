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

    def __init__(self, lang: str = 'en', mask_dilation: int = 5):
        """
        :param lang: Язык субтитров ('en', 'ru' и т.д.)
        :param mask_dilation: На сколько пикселей расширять маску вокруг текста.
                              Больше = лучше убирает края, но мылит фон.
        """
        if PaddleOCR is None:
            raise ImportError("PaddleOCR not installed. Cannot remove subtitles.")
            
        self.lang = lang
        self.mask_dilation = mask_dilation
        logger.info(f"Initializing SubtitleRemoverNative (lang={lang}, CPU)...")
        # Initialize PaddleOCR with language setting
        # Note: use_gpu and show_log parameters are deprecated in newer versions
        self.ocr = PaddleOCR(lang=lang)
        logger.info("PaddleOCR initialized successfully.")

    def process_frames(self, input_dir: Path, output_dir: Path) -> None:
        """
        Обрабатывает все изображения в input_dir и сохраняет в output_dir.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Получаем список файлов (png/jpg)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        total = len(frames)

        logger.info(f"Starting subtitle removal on {total} frames...")

        for idx, frame_path in enumerate(frames):
            try:
                self._process_single_frame(frame_path, output_dir / frame_path.name)

                # Show progress for every frame when processing small batches
                if total <= 10:
                    logger.info(f"Processed {idx+1}/{total} frames: {frame_path.name}")
                elif (idx + 1) % 10 == 0 or (idx + 1) == total:
                    logger.info(f"Processed {idx+1}/{total} frames...")
            except Exception as e:
                logger.error(f"Failed to process frame {frame_path}: {e}")
                # В случае ошибки просто копируем оригинал, чтобы не ломать видео
                import shutil
                shutil.copy(frame_path, output_dir / frame_path.name)

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
                        # Filter by confidence (only process high-confidence detections)
                        if conf > 0.5:
                            # Convert polygon to correct format for fillPoly
                            # poly is numpy array of shape (n, 2)
                            points = poly.astype(np.int32).reshape((-1, 1, 2))
                            cv2.fillPoly(mask, [points], 255)
                            boxes_found = True
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
                    
                    # Filter by confidence (only process high-confidence detections)
                    if conf > 0.5:
                        points = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                        cv2.fillPoly(mask, [points], 255)
                        boxes_found = True
                except (IndexError, TypeError, ValueError) as e:
                    logger.warning(f"Failed to parse OCR result line: {line}, error: {e}")
                    continue

        if not boxes_found:
            cv2.imwrite(str(output_path), img)
            return

        # 4. Расширение маски (Dilation)
        # Это нужно, чтобы убрать артефакты сжатия вокруг букв
        kernel = np.ones((self.mask_dilation, self.mask_dilation), np.uint8)
        dilated_mask = cv2.dilate(mask, kernel, iterations=1)

        # 5. Inpainting (Закрашивание)
        # cv2.INPAINT_TELEA или cv2.INPAINT_NS. Telea обычно быстрее и дает меньше артефактов на тексте.
        result_img = cv2.inpaint(img, dilated_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

        # 6. Сохранение
        cv2.imwrite(str(output_path), result_img)
