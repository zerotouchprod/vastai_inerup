"""
Утилиты для работы с видео и кадрами.
"""

import numpy as np
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


def read_video(path: str, gray: bool = False) -> Tuple[np.ndarray, float]:
    """
    Читает видео кадры из директории или видео файла.
    
    Args:
        path: Путь к директории с кадрами или видео файлу
        gray: Конвертировать в оттенки серого
    
    Returns:
        Tuple[frames, fps] где frames - numpy массив формы (T, H, W, C)
        с C=1 если gray иначе 3, значения 0-255.
    """
    try:
        # Пытаемся импортировать из ProPainter
        import sys
        import os
        PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
        if PROPAINTER_ROOT not in sys.path:
            sys.path.append(PROPAINTER_ROOT)
        
        from inference_propainter import read_frame_from_videos
        
        frames, fps, size, video_name = read_frame_from_videos(path)
        
        # Конвертируем PIL Images в numpy массивы
        arrs = []
        for f in frames:
            if gray:
                # Конвертируем в оттенки серого
                f = f.convert('L')
                arr = np.array(f, dtype=np.uint8)
                arr = arr[..., np.newaxis]  # добавляем channel dimension
            else:
                # Обеспечиваем RGB
                f = f.convert('RGB')
                arr = np.array(f, dtype=np.uint8)
            arrs.append(arr)
        
        # Собираем вдоль временной оси
        video = np.stack(arrs, axis=0)
        return video, fps
        
    except ImportError as e:
        logger.warning(f"ProPainter modules not found: {e}. Using fallback implementation.")
        return _read_video_fallback(path, gray)


def _read_video_fallback(path: str, gray: bool = False) -> Tuple[np.ndarray, float]:
    """
    Fallback реализация чтения видео через OpenCV.
    
    Args:
        path: Путь к директории с кадрами или видео файлу
        gray: Конвертировать в оттенки серого
    
    Returns:
        Tuple[frames, fps]
    """
    import cv2
    from pathlib import Path
    
    path_obj = Path(path)
    
    if path_obj.is_dir():
        # Чтение кадров из директории
        frames = []
        extensions = ['*.png', '*.jpg', '*.jpeg', '*.bmp']
        
        for ext in extensions:
            frame_files = sorted(path_obj.glob(ext))
            for frame_file in frame_files:
                if gray:
                    img = cv2.imread(str(frame_file), cv2.IMREAD_GRAYSCALE)
                    img = img[..., np.newaxis]  # добавляем channel dimension
                else:
                    img = cv2.imread(str(frame_file))
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                frames.append(img)
        
        if not frames:
            raise ValueError(f"No frames found in directory: {path}")
        
        video = np.stack(frames, axis=0)
        # Предполагаем 30 FPS по умолчанию для директорий
        fps = 30.0
        
    else:
        # Чтение из видео файла
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = []
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if gray:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                frame = frame[..., np.newaxis]
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            frames.append(frame)
        
        cap.release()
        
        if not frames:
            raise ValueError(f"No frames read from video: {path}")
        
        video = np.stack(frames, axis=0)
    
    return video, fps


def save_frames(frames: np.ndarray, output_dir: str, prefix: str = "frame"):
    """
    Сохраняет кадры в директорию.
    
    Args:
        frames: Массив кадров формы (T, H, W, C) или (T, H, W) для grayscale
        output_dir: Директория для сохранения
        prefix: Префикс для имен файлов
    """
    import cv2
    from pathlib import Path
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for i, frame in enumerate(frames):
        if len(frame.shape) == 3 and frame.shape[2] == 3:
            # RGB to BGR для OpenCV
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        elif len(frame.shape) == 2:
            # Grayscale
            pass
        
        filename = output_path / f"{prefix}_{i:04d}.png"
        cv2.imwrite(str(filename), frame)
    
    logger.info(f"Saved {len(frames)} frames to {output_dir}")
