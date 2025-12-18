"""
Упрощенная версия ProPainter wrapper с улучшенным управлением памятью.
Основные исправления:
1. Уменьшен размер чанков для нового API (7 аргументов)
2. Добавлены переменные окружения PyTorch для управления памятью
3. Агрессивная очистка памяти между чанками
4. Fallback на CPU при нехватке памяти
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
from typing import List

# Настраиваем переменные окружения PyTorch для лучшего управления памятью
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:128'
os.environ['CUDA_LAUNCH_BLOCKING'] = '0'

logger = logging.getLogger(__name__)

class SubtitleRemoverProPainterSimple:
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        self.lang = lang
        self.mask_dilation = mask_dilation
        
        # Определяем устройство
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            logger.info(f"Using CUDA device: {self.device}")
            logger.info(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
        else:
            self.device = torch.device("cpu")
            logger.info("Using CPU device")
        
        # Загружаем модель ProPainter
        PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        
        sys.path.append(PROPAINTER_ROOT)
        from model.propainter import InpaintGenerator
        from inference_propainter import read_frame_from_videos
        
        self.model = InpaintGenerator(model_path=str(weights_path))
        self.model = self.model.to(self.device)
        self.model.eval()
        
        # Используем mixed precision для экономии VRAM
        from torch.cuda.amp import autocast
        self.autocast = autocast
        
        logger.info("ProPainter model loaded successfully")

    def _call_propainter_api(self, frames, masks):
        """
        Гибкий вызов API ProPainter с поддержкой 7 аргументов.
        """
        b, t, c, h, w = frames.shape
        
        # Создаем пустой тензор для completed_flows
        completed_flows = torch.zeros((b, t-1, 2, h, w), device=frames.device)
        
        # Вызываем API с 7 аргументами
        if self.autocast is not None:
            with self.autocast():
                return self.model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)
        else:
            return self.model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)

    def process_frames(self, input_dir: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Читаем видео
        from inference_propainter import read_frame_from_videos
        
        frames, fps, size, video_name = read_frame_from_videos(str(input_dir))
        video_frames = np.stack([np.array(f.convert('RGB')) for f in frames], axis=0)
        
        # Создаем простые маски (для теста - весь нижний регион)
        h, w = video_frames.shape[1:3]
        video_masks = np.zeros((len(frames), h, w, 1), dtype=np.uint8)
        video_masks[:, h//2:, :, :] = 255  # Маска на нижней половине
        
        # Подготовка тензоров
        video_frames_t = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
        video_masks_t = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
        
        total_frames = video_frames_t.shape[0]
        
        # ОПТИМИЗАЦИЯ ПАМЯТИ: уменьшаем размер чанков
        if self.device.type == 'cuda':
            # Для нового API с 7 аргументами требуется больше памяти
            # Используем очень маленькие чанки
            max_frames_per_chunk = 8  # Вместо 30
            logger.info(f"GPU optimization: processing {total_frames} frames in chunks of {max_frames_per_chunk}")
        else:
            max_frames_per_chunk = 15
        
        pred_chunks = []
        
        for chunk_start in range(0, total_frames, max_frames_per_chunk):
            chunk_end = min(chunk_start + max_frames_per_chunk, total_frames)
            logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_frames}")
            
            # Вырезаем чанк
            frames_chunk = video_frames_t[chunk_start:chunk_end].unsqueeze(0).to(self.device)
            masks_chunk = video_masks_t[chunk_start:chunk_end].unsqueeze(0).to(self.device)
            masks_chunk = (masks_chunk > 0.5).float()
            
            # Создаем входное видео с "дырками"
            masked_input = frames_chunk * (1 - masks_chunk)
            
            # Ресайз если нужно
            b, t, c, h, w = masked_input.shape
            pad_h = (8 - h % 8) % 8
            pad_w = (8 - w % 8) % 8
            if pad_h > 0 or pad_w > 0:
                import torch.nn.functional as F
                masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
                masks_chunk = F.pad(masks_chunk, (0, pad_w, 0, pad_h))
            
            # Inference
            inference_start = time.time()
            with torch.no_grad():
                try:
                    pred_chunk = self._call_propainter_api(masked_input, masks_chunk)
                except torch.cuda.OutOfMemoryError:
                    logger.error("CUDA out of memory! Falling back to CPU...")
                    
                    # Fallback на CPU
                    masked_input_cpu = masked_input.cpu()
                    masks_chunk_cpu = masks_chunk.cpu()
                    self.model.cpu()
                    
                    torch.cuda.empty_cache()
                    
                    pred_chunk = self._call_propainter_api(masked_input_cpu, masks_chunk_cpu)
                    
                    # Возвращаем модель на GPU
                    if self.device.type == 'cuda':
                        self.model.to(self.device)
            
            inference_time = time.time() - inference_start
            logger.info(f"Chunk {chunk_start}-{chunk_end} completed in {inference_time:.1f}s ({t/inference_time:.1f} FPS)")
            
            # Убираем паддинг
            pred_chunk = pred_chunk[0, :, :, :h, :w]
            pred_chunks.append(pred_chunk.cpu())
            
            # АГРЕССИВНАЯ ОЧИСТКА ПАМЯТИ
            if self.device.type == 'cuda':
                del masked_input, masks_chunk, pred_chunk
                torch.cuda.empty_cache()
                import gc
                gc.collect()
                
                allocated = torch.cuda.memory_allocated() / 1e9
                logger.info(f"GPU memory after cleanup: {allocated:.2f} GB")
        
        # Объединяем все чанки
        pred_frames = torch.cat(pred_chunks, dim=0)
        
        # Сохраняем
        pred_frames = pred_frames.permute(0, 2, 3, 1).cpu().numpy() * 255.0
        pred_frames = pred_frames.astype(np.uint8)
        
        for i, frame in enumerate(pred_frames):
            cv2.imwrite(str(output_dir / f"frame_{i:04d}.png"), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        
        logger.info(f"Saved {len(pred_frames)} processed frames")

# Тестовая функция
def test_propainter_memory():
    """Тестируем ProPainter с улучшенным управлением памятью"""
    import tempfile
    import shutil
    
    # Создаем тестовые кадры
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        
        # Создаем 50 тестовых кадров
        for i in range(50):
            img = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
            cv2.imwrite(str(input_dir / f"frame_{i:04d}.png"), img)
        
        # Обрабатываем
        processor = SubtitleRemoverProPainterSimple()
        processor.process_frames(input_dir, output_dir)
        
        print(f"✅ Обработано {len(list(output_dir.glob('*.png')))} кадров")
        print(f"✅ Память GPU: {torch.cuda.memory_allocated() / 1e9:.2f} GB")

if __name__ == "__main__":
    test_propainter_memory()
