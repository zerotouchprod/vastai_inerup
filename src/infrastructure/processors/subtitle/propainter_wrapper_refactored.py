"""
Рефакторированная версия ProPainter wrapper с улучшенной архитектурой.

Основные изменения:
1. Изолированы утилиты в отдельные модули
2. Декомпозирован __init__ на понятные подзадачи
3. Выделен генератор масок в отдельный класс
4. Упрощен цикл обработки
5. Стабилизирован API ProPainter (определяется один раз при инициализации)
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
from typing import List, Optional, Tuple, Callable
import inspect

from domain.models import ProcessingResult

# Импортируем утилиты
from src.infrastructure.utils.paddle_utils import setup_paddle_logging, init_paddle_ocr, SuppressPaddleOutput
from src.infrastructure.utils.video_utils import read_video

logger = logging.getLogger(__name__)


class MaskGenerator:
    """Класс для генерации масок субтитров с использованием PaddleOCR."""
    
    def __init__(self, lang: str = 'en', mask_dilation: int = 12, use_gpu_for_ocr: bool = False):
        """
        Инициализирует генератор масок.
        
        Args:
            lang: Язык для OCR
            mask_dilation: Радиус расширения маски в пикселях
            use_gpu_for_ocr: Использовать GPU для OCR если доступно
        """
        self.lang = lang
        self.mask_dilation = mask_dilation
        self.use_gpu_for_ocr = use_gpu_for_ocr
        self.ocr = None
        
        # Настраиваем логирование PaddleOCR
        setup_paddle_logging()
        
    def _init_ocr(self):
        """Инициализирует PaddleOCR."""
        if self.ocr is None:
            self.ocr = init_paddle_ocr(
                lang=self.lang,
                use_gpu_for_ocr=self.use_gpu_for_ocr,
                use_angle_cls=False
            )
            if self.ocr is None:
                raise ImportError("PaddleOCR not installed. Cannot remove subtitles.")
        
        return self.ocr
    
    def generate(self, input_dir: Path, output_dir: Path, batch_size: int = 8) -> Path:
        """
        Генерирует маски для всех кадров в директории.
        
        Args:
            input_dir: Директория с входными кадрами
            output_dir: Директория для сохранения масок
            batch_size: Размер батча для обработки
        
        Returns:
            Путь к директории с масками
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            raise ValueError(f"No frames found in directory: {input_dir}")
        
        logger.info(f"Generating masks for {len(frames)} frames (batch size: {batch_size})...")
        
        # Обрабатываем батчами
        for i in range(0, len(frames), batch_size):
            batch = frames[i:i + batch_size]
            self._create_masks_batch(batch, output_dir)
            
            processed = min(i + batch_size, len(frames))
            if (i + batch_size) % (batch_size * 5) == 0 or processed == len(frames):
                logger.info(f"Created masks for {processed}/{len(frames)} frames")
        
        return output_dir
    
    def _create_masks_batch(self, img_paths: List[Path], output_dir: Path):
        """Создает маски для батча изображений."""
        if not img_paths:
            return
            
        import concurrent.futures
        import threading
        
        # Используем локальное хранилище для потоков
        thread_local = threading.local()
        
        def get_ocr():
            """Получаем экземпляр OCR для текущего потока."""
            if not hasattr(thread_local, "ocr"):
                # Создаем отдельный экземпляр OCR для каждого потока
                thread_local.ocr = init_paddle_ocr(
                    lang=self.lang,
                    use_gpu_for_ocr=self.use_gpu_for_ocr,
                    use_angle_cls=False
                )
            return thread_local.ocr
        
        # Загружаем все изображения параллельно
        images = []
        valid_paths = []
        
        def load_image(img_path):
            img = cv2.imread(str(img_path))
            return img, img_path
        
        # Используем ThreadPoolExecutor для параллельной загрузки изображений
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_path = {executor.submit(load_image, img_path): img_path for img_path in img_paths}
            for future in concurrent.futures.as_completed(future_to_path):
                img, img_path = future.result()
                if img is not None:
                    images.append(img)
                    valid_paths.append(img_path)
        
        if not images:
            return
            
        # Оптимизация: уменьшаем разрешение для OCR если изображения большие
        max_ocr_dim = 480
        
        # Подготавливаем изображения для OCR
        ocr_images = []
        scale_factors = []
        original_shapes = []
        
        for img in images:
            h, w = img.shape[:2]
            original_shapes.append((h, w))
            
            # Если изображение слишком большое, уменьшаем его для OCR
            if max(h, w) > max_ocr_dim:
                scale = max_ocr_dim / max(h, w)
                new_h, new_w = int(h * scale), int(w * scale)
                resized = cv2.resize(img, (new_w, new_h))
                ocr_images.append(resized)
                scale_factors.append(scale)
            else:
                ocr_images.append(img)
                scale_factors.append(1.0)
        
        # Функция для обработки одного изображения
        def process_single_image(args):
            i, ocr_img, img_path, scale_factor, orig_h, orig_w = args
            
            mask = np.zeros((orig_h, orig_w), dtype=np.uint8)
            
            # Получаем OCR для текущего потока
            ocr = get_ocr()
            
            # Выполняем OCR на уменьшенном изображении
            result = ocr.ocr(ocr_img)
            
            if result:
                # Масштабируем координаты обратно к оригинальному размеру
                scale_inv = 1.0 / scale_factor if scale_factor != 1.0 else 1.0
                
                for ocr_result in result:
                    if hasattr(ocr_result, 'rec_polys'):
                        polys = ocr_result.rec_polys
                        scores = ocr_result.rec_scores
                    elif isinstance(ocr_result, dict) and 'rec_polys' in ocr_result:
                        polys = ocr_result['rec_polys']
                        scores = ocr_result['rec_scores']
                    else:
                        # Old format
                        if isinstance(ocr_result, list):
                            for line in ocr_result:
                                if isinstance(line, (list, tuple)) and len(line) >= 2:
                                    coords = line[0]
                                    if isinstance(line[1], (list, tuple)) and len(line[1]) >= 2:
                                        conf = line[1][1]
                                    else:
                                        conf = 0.0
                                    if conf > 0.4:
                                        # Масштабируем координаты
                                        scaled_coords = [(int(x * scale_inv), int(y * scale_inv)) for x, y in coords]
                                        pts = np.array(scaled_coords, dtype=np.int32).reshape((-1, 1, 2))
                                        cv2.fillPoly(mask, [pts], 255)
                        continue
                    
                    # Process new format
                    if polys is not None and scores is not None:
                        for poly, score in zip(polys, scores):
                            if score > 0.4:
                                # Масштабируем координаты
                                scaled_poly = poly * scale_inv
                                pts = scaled_poly.astype(np.int32).reshape((-1, 1, 2))
                                cv2.fillPoly(mask, [pts], 255)
            
            # Агрессивное расширение для Glow
            if self.mask_dilation > 0:
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            # Сохраняем маску
            mask_path = output_dir / img_path.name
            cv2.imwrite(str(mask_path), mask)
            
            return True
        
        # Подготавливаем аргументы для параллельной обработки
        args_list = []
        for i, (img, ocr_img, img_path, scale_factor, (orig_h, orig_w)) in enumerate(
            zip(images, ocr_images, valid_paths, scale_factors, original_shapes)):
            args_list.append((i, ocr_img, img_path, scale_factor, orig_h, orig_w))
        
        # Обрабатываем изображения параллельно
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(process_single_image, args_list))


class SubtitleRemoverProPainter:
    """Основной класс для удаления субтитров с использованием ProPainter."""
    
    def __init__(self, lang: str = 'en', mask_dilation: int = 12, use_gpu_for_ocr: bool = False):
        """
        Инициализирует ProPainter Subtitle Remover.
        
        Args:
            lang: Язык для OCR
            mask_dilation: Радиус расширения маски в пикселях
            use_gpu_for_ocr: Использовать GPU для OCR если доступно
        """
        self.lang = lang
        self.mask_dilation = mask_dilation
        self.use_gpu_for_ocr = use_gpu_for_ocr
        
        logger.info(f"Initializing ProPainter Subtitle Remover (lang={lang}, dilation={mask_dilation})")
        
        # Инициализируем компоненты
        self.device = self._init_device()
        self.mask_generator = MaskGenerator(lang=lang, mask_dilation=mask_dilation, use_gpu_for_ocr=use_gpu_for_ocr)
        self.model, self.forward_method = self._init_propainter_model()
        
        logger.info("ProPainter Subtitle Remover initialized successfully")
    
    def _init_device(self) -> torch.device:
        """Инициализирует устройство (CPU/CUDA) с безопасным fallback."""
        # Настраиваем переменные окружения PyTorch для лучшего управления памятью
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:128'
        os.environ['CUDA_LAUNCH_BLOCKING'] = '0'
        
        cuda_available = False
        cuda_error = None
        
        try:
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                device_count = torch.cuda.device_count()
                if device_count > 0:
                    device_name = torch.cuda.get_device_name(0)
                    logger.info(f"CUDA GPU detected: {device_name}")
                    logger.info(f"CUDA version: {torch.version.cuda}")
                else:
                    cuda_available = False
                    logger.warning("CUDA available but no GPU devices found")
        except Exception as e:
            cuda_available = False
            cuda_error = str(e)
            logger.warning(f"CUDA check failed: {e}")
        
        # Выбираем устройство с безопасным fallback
        if cuda_available:
            try:
                device = torch.device("cuda")
                # Тестируем устройство простой операцией
                test_tensor = torch.tensor([1.0]).cuda()
                del test_tensor
                torch.cuda.empty_cache()
                logger.info(f"Using CUDA device: {device}")
                logger.info(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
                return device
            except Exception as e:
                logger.error(f"CUDA device failed: {e}. Falling back to CPU.")
                return torch.device("cpu")
        else:
            if cuda_error:
                logger.warning(f"CUDA not available: {cuda_error}. Using CPU.")
            else:
                logger.info("Using CPU device")
            return torch.device("cpu")
    
    def _init_propainter_model(self) -> Tuple[torch.nn.Module, Callable]:
        """
        Инициализирует модель ProPainter и определяет метод forward.
        
        Returns:
            Tuple[model, forward_method] где forward_method - адаптированный метод вызова
        """
        # Добавляем путь к ProPainter в sys.path
        PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
        if PROPAINTER_ROOT not in sys.path:
            sys.path.append(PROPAINTER_ROOT)
        
        try:
            from model.propainter import InpaintGenerator
        except ImportError as e:
            logger.error(f"Failed to import ProPainter modules: {e}")
            raise ImportError(f"ProPainter modules not found. Make sure they are in {PROPAINTER_ROOT}")
        
        # Загружаем веса
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        if not weights_path.exists():
            raise FileNotFoundError(f"Weights not found: {weights_path}")
        
        logger.info(f"Loading ProPainter model from {weights_path}")
        
        # Создаем модель на CPU сначала
        logger.info("Creating ProPainter model on CPU...")
        model = InpaintGenerator(model_path=str(weights_path))
        
        # Перемещаем на устройство если доступно
        if self.device.type == 'cuda':
            try:
                logger.info("Moving model to CUDA device...")
                model = model.to(self.device)
                
                # Проверяем, что модель действительно на GPU
                model_device = next(model.parameters()).device
                if model_device.type == 'cuda':
                    # Очищаем кэш CUDA
                    torch.cuda.empty_cache()
                    
                    # Мониторинг памяти
                    allocated = torch.cuda.memory_allocated() / 1024**3
                    reserved = torch.cuda.memory_reserved() / 1024**3
                    logger.info(f"GPU memory after loading: {allocated:.2f} GB allocated, {reserved:.2f} GB reserved")
                    
                    # Используем mixed precision для экономии VRAM
                    from torch.cuda.amp import autocast
                    self.autocast = autocast
                    logger.info("Mixed precision (autocast) enabled")
                else:
                    logger.warning(f"Model loaded on {model_device}, expected cuda")
                    self.autocast = None
            except Exception as e:
                logger.error(f"Failed to move model to CUDA: {e}. Keeping on CPU.")
                self.device = torch.device("cpu")
                self.autocast = None
        else:
            self.autocast = None
        
        model.eval()
        
        # Определяем метод forward один раз при инициализации
        forward_method = self._inspect_model_signature(model)
        
        # Проверяем устройство модели
        model_device = next(model.parameters()).device
        logger.info(f"ProPainter model loaded on device: {model_device}")
        
        return model, forward_method
    
    def _inspect_model_signature(self, model: torch.nn.Module) -> Callable:
        """
        Определяет сигнатуру метода forward модели и возвращает адаптированный метод.
        
        Args:
            model: Модель ProPainter
        
        Returns:
            Адаптированный метод вызова модели
        """
        try:
            sig = inspect.signature(model.forward)
            params = list(sig.parameters.keys())
            logger.info(f"Model forward signature: {sig}")
            logger.info(f"Parameters: {params}")
            logger.info(f"Number of parameters: {len(params)}")
            
            # Создаем адаптированный метод на основе сигнатуры
            if len(params) == 2:
                # Старый API: forward(frames, masks)
                def forward_adapter(frames, masks):
                    return model(frames, masks)
            elif len(params) == 3:
                # Промежуточный API: forward(frames, masks_in, masks_updated)
                def forward_adapter(frames, masks):
                    return model(frames, masks, masks)
            elif len(params) == 4:
                # Новый API: forward(frames, masks_in, masks_updated, num_local_frames)
                def forward_adapter(frames, masks):
                    return model(frames, masks, masks, 10)
            elif len(params) == 5:
                # API: forward(frames, masks_in, masks_updated, num_local_frames, device)
                def forward_adapter(frames, masks):
                    return model(frames, masks, masks, 10, self.device)
            elif len(params) == 7:
                # Самый новый API: forward(masked_frames, completed_flows, masks_in, masks_updated, num_local_frames, interpolation, t_dilation)
                def forward_adapter(frames, masks):
                    b, t, c, h, w = frames.shape
                    completed_flows = torch.zeros((b, t-1, 2, h, w), device=frames.device)
                    return model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)
            else:
                raise ValueError(f"Unsupported number of parameters: {len(params)}")
            
            return forward_adapter
            
        except Exception as sig_error:
            logger.warning(f"Could not inspect signature: {sig_error}. Using fallback adapter...")
            
            # Fallback адаптер, который пробует разные варианты API
            def fallback_adapter(frames, masks):
                # Вариант 1: API с 7 аргументами (самый новый)
                try:
                    b, t, c, h, w = frames.shape
                    completed_flows = torch.zeros((b, t-1, 2, h, w), device=frames.device)
                    return model(frames, completed_flows, masks, masks, 10, 'bilinear', 2)
                except (TypeError, AttributeError) as e1:
                    logger.warning(f"API 7-args failed: {e1}")
                    # Вариант 2: API с 5 аргументами
                    try:
                        return model(frames, masks, masks, 10, self.device)
                    except TypeError as e2:
                        logger.warning(f"API 5-args failed: {e2}")
                        # Вариант 3: API с 4 аргументами
                        try:
                            return model(frames, masks, masks, 10)
                        except TypeError as e3:
                            logger.warning(f"API 4-args failed: {e3}")
                            # Вариант 4: API с 3 аргументами
                            try:
                                return model(frames, masks, masks)
                            except TypeError as e4:
                                logger.warning(f"API 3-args failed: {e4}")
                                # Вариант 5: Старый API с 2 аргументами
                                try:
                                    return model(frames, masks)
                                except TypeError as e5:
                                    logger.error(f"All API attempts failed: {e5}")
                                    raise RuntimeError(f"Could not find compatible ProPainter API. Error: {e5}")
            
            return fallback_adapter
    
    def _estimate_max_batch_size(self, frame_height: int, frame_width: int) -> int:
        """
        Оценивает максимальный размер батча на основе доступной памяти.
        
        Args:
            frame_height: Высота кадра
            frame_width: Ширина кадра
        
        Returns:
            Максимальное количество кадров для обработки за раз
        """
        if self.device.type == 'cuda':
            try:
                # Получаем информацию о доступной памяти
                total_memory = torch.cuda.get_device_properties(0).total_memory / 1e9  # GB
                allocated_memory = torch.cuda.memory_allocated() / 1e9
                free_memory = total_memory - allocated_memory
                
                logger.info(f"GPU memory: {total_memory:.2f} GB total, {free_memory:.2f} GB free")
                
                # Эмпирическая формула: каждый кадр 720p требует ~0.1 GB памяти
                # Безопасный коэффициент: используем только 70% свободной памяти
                safe_memory = free_memory * 0.7
                estimated_frames_per_gb = 10  # 10 кадров на GB для 720p
                max_frames_per_chunk = int(safe_memory * estimated_frames_per_gb)
                
                # Ограничения: минимум 5, максимум 30 кадров
                max_frames_per_chunk = max(5, min(max_frames_per_chunk, 30))
                
                logger.info(f"Estimated max batch size: {max_frames_per_chunk} frames")
                return max_frames_per_chunk
            except Exception as e:
                logger.warning(f"Could not determine GPU memory, using default: {e}")
                return 15  # Безопасное значение по умолчанию
        else:
            return 30  # Для CPU можно больше
    
    def _process_in_chunks(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Обрабатывает кадры частями для экономии памяти.
        
        Args:
            frames: Тензор кадров формы (T, C, H, W)
            masks: Тензор масок формы (T, 1, H, W)
        
        Returns:
            Тензор обработанных кадров
        """
        total_frames = frames.shape[0]
        max_frames_per_chunk = self._estimate_max_batch_size(frames.shape[2], frames.shape[3])
        
        if total_frames <= max_frames_per_chunk:
            # Обрабатываем все кадры сразу
            return self._process_single_chunk(frames, masks)
        
        # Обрабатываем частями
        logger.info(f"Processing {total_frames} frames in chunks of {max_frames_per_chunk}")
        
        pred_chunks = []
        for chunk_start in range(0, total_frames, max_frames_per_chunk):
            chunk_end = min(chunk_start + max_frames_per_chunk, total_frames)
            logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_frames}")
            
            # Вырезаем чанк
            frames_chunk = frames[chunk_start:chunk_end].unsqueeze(0).to(self.device)
            masks_chunk = masks[chunk_start:chunk_end].unsqueeze(0).to(self.device)
            masks_chunk = (masks_chunk > 0.5).float()
            
            # Обрабатываем чанк
            pred_chunk = self._process_single_chunk(frames_chunk, masks_chunk)
            pred_chunks.append(pred_chunk.cpu())
            
            # Очищаем память
            if self.device.type == 'cuda':
                torch.cuda.empty_cache()
        
        # Объединяем все чанки
        return torch.cat(pred_chunks, dim=0)
    
    def _process_single_chunk(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Обрабатывает один чанк кадров.
        
        Args:
            frames: Тензор кадров формы (1, T, C, H, W)
            masks: Тензор масок формы (1, T, 1, H, W)
        
        Returns:
            Тензор обработанных кадров формы (T, C, H, W)
        """
        # Создаем входное видео с "дырками"
        masked_input = frames * (1 - masks)
        
        # Ресайз если нужно (кратно 8)
        b, t, c, h, w = masked_input.shape
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8
        
        if pad_h > 0 or pad_w > 0:
            import torch.nn.functional as F
            masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
            masks = F.pad(masks, (0, pad_w, 0, pad_h))
        
        # Inference
        inference_start = time.time()
        with torch.no_grad():
            if self.autocast is not None:
                with self.autocast():
                    pred_frames = self.forward_method(masked_input, masks)
            else:
                pred_frames = self.forward_method(masked_input, masks)
        
        inference_time = time.time() - inference_start
        logger.info(f"Chunk processed in {inference_time:.1f}s ({t/inference_time:.1f} FPS)")
        
        # Убираем паддинг
        pred_frames = pred_frames[0, :, :, :h, :w]
        
        return pred_frames
    
    def process_frames(self, input_dir: Path, output_dir: Path):
        """
        Основной метод обработки кадров.
        
        Args:
            input_dir: Директория с входными кадрами
            output_dir: Директория для сохранения обработанных кадров
        """
        import time
        start_time = time.time()
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Генерация масок
        logger.info("Step 1/2: Generating masks...")
        tmp_mask_dir = output_dir.parent / "tmp_masks_propainter"
        if tmp_mask_dir.exists():
            shutil.rmtree(tmp_mask_dir)
        
        mask_dir = self.mask_generator.generate(input_dir, tmp_mask_dir)
        
        # 2. Чтение видео и масок
        logger.info("Step 2/2: Running AI Inpainting (ProPainter)...")
        video_frames, _ = read_video(str(input_dir))
        video_masks, _ = read_video(str(mask_dir), gray=True)
        
        # Подготовка тензоров
        video_frames_t = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
        video_masks_t = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
        
        # 3. Обработка кадров
        pred_frames = self._process_in_chunks(video_frames_t, video_masks_t)
        
        # 4. Сохранение результатов
        pred_frames = pred_frames.permute(0, 2, 3, 1).cpu().numpy() * 255.0
        pred_frames = pred_frames.astype(np.uint8)
        
        logger.info(f"Saving {len(pred_frames)} processed frames...")
        
        # Сохраняем кадры
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        for i, frame in enumerate(pred_frames):
            original_name = frames[i].name
            cv2.imwrite(str(output_dir / original_name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        
        # 5. Очистка
        shutil.rmtree(tmp_mask_dir)
        
        total_time = time.time() - start_time
        logger.info(f"ProPainter processing complete. Total time: {total_time:.1f} seconds")
        logger.info(f"Average speed: {len(pred_frames) / total_time:.1f} FPS")


class SubtitleRemoverProPainterWrapper:
    """Wrapper for ProPainter subtitle removal processor implementing IProcessor."""
    
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        """
        Initialize ProPainter subtitle remover.

        Args:
            lang: Language for OCR ('en', 'ru', etc.)
            mask_dilation: Mask dilation radius in pixels
        """
        self._lang = lang
        self._mask_dilation = mask_dilation
        self._processor = None
        self._logger = logging.getLogger(__name__)

    def process(self, input_frames: List[Path], output_dir: Path, **options) -> ProcessingResult:
        """
        Process frames to remove subtitles using ProPainter.

        Args:
            input_frames: List of input frame paths
            output_dir: Output directory for processed frames
            **options: Additional options (ignored for now)

        Returns:
            ProcessingResult with success status
        """
        import time
        start_time = time.time()

        try:
            # Create processor if not exists
            if self._processor is None:
                self._processor = SubtitleRemoverProPainter(
                    lang=self._lang,
                    mask_dilation=self._mask_dilation
                )

            # Create temporary input directory
            import tempfile
            import shutil
            with tempfile.TemporaryDirectory(prefix="subs_input_") as tmp_input:
                tmp_input_path = Path(tmp_input)
                # Copy frames to temporary directory
                for frame in input_frames:
                    shutil.copy2(frame, tmp_input_path / frame.name)

                # Process frames
                self._processor.process_frames(tmp_input_path, output_dir)

            duration = time.time() - start_time

            # Count output frames
            output_frames = list(output_dir.glob("*.png")) + list(output_dir.glob("*.jpg"))
            
            return ProcessingResult(
                success=True,
                output_path=output_dir,
                frames_processed=len(output_frames),
                duration_seconds=duration,
                metrics={
                    'frames_processed': len(output_frames),
                    'duration_per_frame': duration / len(input_frames) if input_frames else 0,
                    'processor': 'subtitle_remover_propainter'
                }
            )

        except Exception as e:
            self._logger.exception(f"ProPainter subtitle removal failed: {e}")
            return ProcessingResult(
                success=False,
                output_path=None,
                frames_processed=0,
                duration_seconds=time.time() - start_time,
                errors=[str(e)]
            )

    @classmethod
    def is_available(cls) -> bool:
        """Check if ProPainter subtitle remover is available."""
        try:
            import cv2
            import torch
            import numpy as np
            from paddleocr import PaddleOCR  # noqa: F401
            
            # Check if ProPainter modules are available
            PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
            if PROPAINTER_ROOT not in sys.path:
                sys.path.append(PROPAINTER_ROOT)
            
            try:
                from model.propainter import InpaintGenerator
                from inference_propainter import read_frame_from_videos
                
                # Check if weights exist
                weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
                if not weights_path.exists():
                    logger.warning(f"ProPainter weights not found: {weights_path}")
                    return False
                    
                return True
            except ImportError:
                logger.warning("ProPainter modules not found")
                return False
                
        except ImportError:
            return False

    def supports_gpu(self) -> bool:
        """Check if GPU is supported (ProPainter uses GPU if available)."""
        return torch.cuda.is_available()
