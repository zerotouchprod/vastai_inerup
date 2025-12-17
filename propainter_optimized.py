#!/usr/bin/env python3
"""
Оптимизированная версия ProPainter wrapper с улучшенной производительностью.
"""

import os
import sys
import cv2
import torch
import logging
import numpy as np
import shutil
from pathlib import Path
import time
from typing import List, Dict, Optional
from functools import lru_cache

logger = logging.getLogger(__name__)

class OptimizedSubtitleRemoverProPainter:
    """
    Оптимизированная версия ProPainter для удаления субтитров.
    """
    
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.lang = lang
        self.mask_dilation = mask_dilation
        
        # Кэш для OCR результатов (чтобы не обрабатывать одинаковые кадры)
        self.ocr_cache: Dict[str, list] = {}
        
        # Инициализация PaddleOCR с минимальными параметрами
        from paddleocr import PaddleOCR
        self.ocr = PaddleOCR(lang=lang, use_angle_cls=False)
        
        # Инициализация ProPainter
        PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
        sys.path.append(PROPAINTER_ROOT)
        
        from model.propainter import InpaintGenerator
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        self.model = InpaintGenerator(model_path=str(weights_path)).to(self.device)
        self.model.eval()
        
        logger.info(f"Optimized ProPainter initialized on {self.device}")
    
    @lru_cache(maxsize=100)
    def _get_frame_hash(self, img_path: Path) -> str:
        """Получить хэш кадра для кэширования."""
        import hashlib
        with open(img_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    
    def _detect_text_regions(self, img: np.ndarray) -> Optional[list]:
        """Обнаружение текстовых регионов с кэшированием."""
        # Конвертируем изображение в байты для хэширования
        import hashlib
        img_bytes = cv2.imencode('.png', img)[1].tobytes()
        img_hash = hashlib.md5(img_bytes).hexdigest()
        
        # Проверяем кэш
        if img_hash in self.ocr_cache:
            return self.ocr_cache[img_hash]
        
        # Выполняем OCR
        result = self.ocr.ocr(img)
        
        # Кэшируем результат
        self.ocr_cache[img_hash] = result
        
        return result
    
    def process_frames_optimized(self, input_dir: Path, output_dir: Path):
        """Оптимизированная обработка кадров."""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Временная папка для масок
        tmp_mask_dir = output_dir.parent / "tmp_masks_optimized"
        if tmp_mask_dir.exists():
            shutil.rmtree(tmp_mask_dir)
        tmp_mask_dir.mkdir()
        
        # Получаем список кадров
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            logger.error("No frames found!")
            return
        
        total_frames = len(frames)
        logger.info(f"Processing {total_frames} frames with optimized ProPainter...")
        
        # Шаг 1: Генерация масок с оптимизациями
        logger.info("Step 1: Generating masks...")
        mask_start_time = time.time()
        
        # Используем увеличенный размер батча
        batch_size = 16
        processed = 0
        
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i+batch_size]
            self._create_masks_optimized(batch, tmp_mask_dir)
            
            processed += len(batch)
            elapsed = time.time() - mask_start_time
            speed = processed / elapsed if elapsed > 0 else 0
            
            if processed % 40 == 0 or processed >= total_frames:
                logger.info(f"Created masks for {processed}/{total_frames} frames, speed: {speed:.2f} FPS")
        
        # Шаг 2: AI Inpainting
        logger.info("Step 2: Running AI Inpainting...")
        
        # Загружаем видео и маски
        from inference_propainter import read_frame_from_videos
        
        def read_video(path: str, gray: bool = False):
            frames, fps, size, video_name = read_frame_from_videos(path)
            arrs = []
            for f in frames:
                if gray:
                    f = f.convert('L')
                    arr = np.array(f, dtype=np.uint8)
                    arr = arr[..., np.newaxis]
                else:
                    f = f.convert('RGB')
                    arr = np.array(f, dtype=np.uint8)
                arrs.append(arr)
            return np.stack(arrs, axis=0), fps
        
        video_frames, _ = read_video(str(input_dir))
        video_masks, _ = read_video(str(tmp_mask_dir), gray=True)
        
        # Подготовка тензоров
        video_frames = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
        video_masks = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
        
        video_frames = video_frames.unsqueeze(0).to(self.device)
        video_masks = video_masks.unsqueeze(0).to(self.device)
        video_masks = (video_masks > 0.5).float()
        
        # Inpainting
        inference_start = time.time()
        with torch.no_grad():
            pred_frames = self.model(video_frames * (1 - video_masks), video_masks)
        
        inference_time = time.time() - inference_start
        logger.info(f"Inference completed in {inference_time:.1f}s ({len(frames)/inference_time:.1f} FPS)")
        
        # Сохранение результатов
        pred_frames = pred_frames[0].permute(0, 2, 3, 1).cpu().numpy() * 255.0
        pred_frames = pred_frames.astype(np.uint8)
        
        logger.info("Saving processed frames...")
        for i, frame in enumerate(pred_frames):
            original_name = frames[i].name
            cv2.imwrite(str(output_dir / original_name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        
        # Очистка
        shutil.rmtree(tmp_mask_dir)
        
        total_time = time.time() - mask_start_time
        logger.info(f"Total processing time: {total_time:.1f}s ({total_frames/total_time:.1f} FPS)")
    
    def _create_masks_optimized(self, img_paths: List[Path], output_dir: Path):
        """Оптимизированное создание масок."""
        import concurrent.futures
        import threading
        
        # Thread-local OCR
        thread_local = threading.local()
        
        def get_ocr():
            if not hasattr(thread_local, "ocr"):
                from paddleocr import PaddleOCR
                thread_local.ocr = PaddleOCR(lang=self.lang, use_angle_cls=False)
            return thread_local.ocr
        
        # Параллельная загрузка
        images = []
        valid_paths = []
        
        def load_image(img_path):
            return cv2.imread(str(img_path)), img_path
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(load_image, p) for p in img_paths]
            for future in concurrent.futures.as_completed(futures):
                img, path = future.result()
                if img is not None:
                    images.append(img)
                    valid_paths.append(path)
        
        if not images:
            return
        
        # Обработка с увеличенным параллелизмом
        def process_single(args):
            idx, img, img_path = args
            
            # Уменьшение разрешения для OCR
            h, w = img.shape[:2]
            max_dim = 480
            if max(h, w) > max_dim:
                scale = max_dim / max(h, w)
                new_h, new_w = int(h * scale), int(w * scale)
                ocr_img = cv2.resize(img, (new_w, new_h))
                scale_inv = 1.0 / scale
            else:
                ocr_img = img
                scale_inv = 1.0
            
            # OCR
            ocr = get_ocr()
            result = ocr.ocr(ocr_img)
            
            # Создание маски
            mask = np.zeros((h, w), dtype=np.uint8)
            
            if result:
                for ocr_result in result:
                    if isinstance(ocr_result, list):
                        for line in ocr_result:
                            if isinstance(line, (list, tuple)) and len(line) >= 2:
                                coords = line[0]
                                if isinstance(line[1], (list, tuple)) and len(line[1]) >= 2:
                                    conf = line[1][1]
                                else:
                                    conf = 0.0
                                if conf > 0.4:
                                    scaled_coords = [(int(x * scale_inv), int(y * scale_inv)) for x, y in coords]
                                    pts = np.array(scaled_coords, dtype=np.int32).reshape((-1, 1, 2))
                                    cv2.fillPoly(mask, [pts], 255)
            
            # Расширение маски
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            # Сохранение
            cv2.imwrite(str(output_dir / img_path.name), mask)
            return True
        
        # Параллельная обработка с увеличенным количеством потоков
        args_list = [(i, img, path) for i, (img, path) in enumerate(zip(images, valid_paths))]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(process_single, args_list))

# Пример использования
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Тестирование
    input_dir = Path("input_frames")
    output_dir = Path("output_frames")
    
    if input_dir.exists():
        processor = OptimizedSubtitleRemoverProPainter(lang='en')
        processor.process_frames_optimized(input_dir, output_dir)
    else:
        logger.warning(f"Input directory not found: {input_dir}")
