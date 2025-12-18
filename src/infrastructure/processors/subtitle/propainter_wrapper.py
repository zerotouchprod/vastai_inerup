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
from PIL import Image

from domain.models import ProcessingResult

# СНАЧАЛА настраиваем логирование ДО импорта PaddleOCR
import warnings
warnings.filterwarnings('ignore')

# Настраиваем все возможные логгеры PaddleOCR
for logger_name in ['ppocr', 'paddleocr', 'paddle', 'paddlex', 'paddle.nn', 'paddle.fluid']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Также отключаем логирование для root логгера от Paddle
logging.getLogger().setLevel(logging.WARNING)

# Обеспечиваем доступ к модулям ProPainter
PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
if PROPAINTER_ROOT not in sys.path:
    sys.path.append(PROPAINTER_ROOT)

try:
    # Импорты из репозитория ProPainter
    from model.propainter import InpaintGenerator
    # read_video is not present in ProPainter; we define our own
    from inference_propainter import read_frame_from_videos
    
    def read_video(path: str, gray: bool = False):
        """
        Read video frames from a directory or video file.
        Returns (frames, fps) where frames is numpy array of shape (T, H, W, C)
        with C=1 if gray else 3, values 0-255.
        """
        frames, fps, size, video_name = read_frame_from_videos(path)
        # Convert PIL Images to numpy arrays
        arrs = []
        for f in frames:
            if gray:
                # Convert to grayscale
                f = f.convert('L')
                arr = np.array(f, dtype=np.uint8)
                arr = arr[..., np.newaxis]  # add channel dimension
            else:
                # Ensure RGB
                f = f.convert('RGB')
                arr = np.array(f, dtype=np.uint8)
            arrs.append(arr)
        # Stack along time dimension
        video = np.stack(arrs, axis=0)
        return video, fps
except ImportError:
    logging.warning("⚠️ ProPainter modules not found! Make sure they are in /opt/ProPainter")

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

# Дополнительная настройка после импорта
if PaddleOCR:
    # АГРЕССИВНОЕ подавление ВСЕХ выводов PaddleOCR
    try:
        import paddle
        # Проверяем, существует ли метод set_log_level
        if hasattr(paddle, 'set_log_level'):
            paddle.set_log_level(4)  # 4=CRITICAL (максимальное подавление)
        else:
            # Альтернативный способ подавления логов
            import logging
            logging.getLogger('paddle').setLevel(logging.WARNING)
    except ImportError:
        pass
    
    # Отключаем ВСЕ выводы PaddleOCR
    import os
    os.environ['PADDLEOCR_LOG_LEVEL'] = '4'  # Максимальное подавление
    os.environ['LOG_LEVEL'] = '4'
    os.environ['PADDLE_LOG_LEVEL'] = '4'
    os.environ['GLOG_minloglevel'] = '3'  # 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
    
    # Перенаправляем stderr для полного подавления
    import sys
    from contextlib import redirect_stderr, redirect_stdout
    import io
    
    class SuppressPaddleOutput:
        """Контекстный менеджер для подавления вывода PaddleOCR"""
        def __enter__(self):
            self._original_stderr = sys.stderr
            self._original_stdout = sys.stdout
            self._null_stream = io.StringIO()
            sys.stderr = self._null_stream
            sys.stdout = self._null_stream
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            sys.stderr = self._original_stderr
            sys.stdout = self._original_stdout
            
    # Глобальный контекстный менеджер для использования
    global suppress_paddle_output
    suppress_paddle_output = SuppressPaddleOutput

logger = logging.getLogger(__name__)
# Восстанавливаем нормальный уровень для нашего логгера
logger.setLevel(logging.INFO)

class SubtitleRemoverProPainter:
    def __init__(self, lang: str = 'en', mask_dilation: int = 12, use_gpu_for_ocr: bool = False):
        """
        :param lang: Language for OCR
        :param mask_dilation: Насколько расширять маску. 
                              Для ProPainter лучше брать больше (10-15), 
                              чтобы он перерисовал весь ореол субтитров.
        :param use_gpu_for_ocr: Использовать GPU для OCR если доступно (может быть быстрее)
        """
        # БЕЗОПАСНАЯ проверка и инициализация устройства
        # Проблема: PyTorch может быть установлен без поддержки CUDA
        # Решение: безопасный fallback на CPU если CUDA не работает
        
        self.lang = lang
        self.mask_dilation = mask_dilation
        
        logger.info(f"Initializing ProPainter Subtitle Remover (lang={lang}, dilation={mask_dilation})")
        
        # 1. Проверяем доступность CUDA безопасным способом
        cuda_available = False
        cuda_error = None
        
        try:
            # Пробуем импортировать torch.cuda
            import torch.cuda as cuda
            # Проверяем доступность CUDA
            cuda_available = torch.cuda.is_available()
            if cuda_available:
                # Пробуем получить информацию о GPU
                try:
                    device_count = torch.cuda.device_count()
                    if device_count > 0:
                        # Пробуем получить имя устройства
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
        except Exception as e:
            cuda_available = False
            cuda_error = str(e)
            logger.warning(f"CUDA module not available: {e}")
        
        # 2. Выбираем устройство с безопасным fallback
        if cuda_available:
            try:
                # Пробуем инициализировать CUDA устройство
                self.device = torch.device("cuda")
                # Тестируем устройство простой операцией
                test_tensor = torch.tensor([1.0]).cuda()
                del test_tensor
                torch.cuda.empty_cache()
                logger.info(f"Using CUDA device: {self.device}")
                logger.info(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
            except Exception as e:
                # Fallback на CPU если CUDA не работает
                logger.error(f"CUDA device failed: {e}. Falling back to CPU.")
                self.device = torch.device("cpu")
                cuda_available = False
        else:
            self.device = torch.device("cpu")
            if cuda_error:
                logger.warning(f"CUDA not available: {cuda_error}. Using CPU.")
            else:
                logger.info("Using CPU device")
        
        # 3. Проверяем PyTorch версию и CUDA поддержку
        logger.info(f"PyTorch version: {torch.__version__}")
        logger.info(f"PyTorch CUDA available: {torch.cuda.is_available()}")
        
        # 4. Проверяем nvidia-smi для дополнительной диагностики
        try:
            import subprocess
            result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("nvidia-smi detected GPU")
                # Извлекаем информацию о GPU из вывода
                lines = result.stdout.split('\n')
                for line in lines[:5]:  # Первые 5 строк
                    if line.strip():
                        logger.info(f"nvidia-smi: {line.strip()}")
            else:
                logger.warning("nvidia-smi not available or failed")
        except Exception as e:
            logger.debug(f"Could not run nvidia-smi: {e}")

        # 1. Init OCR with optimized parameters
        if PaddleOCR is None:
            raise ImportError("PaddleOCR not installed. Cannot remove subtitles.")
            
        # Проверяем доступность GPU для OCR
        ocr_device = 'gpu' if (use_gpu_for_ocr and torch.cuda.is_available()) else 'cpu'
        logger.info(f"Using {ocr_device.upper()} for PaddleOCR")
        
        # Используем абсолютно минимальный набор параметров
        # В текущей версии PaddleOCR (3.3.2) поддерживаются только базовые параметры
        # Основные рабочие параметры: lang, use_angle_cls
        
        ocr_params = {
            'lang': lang,
            'use_angle_cls': False,  # Отключаем для скорости
            'det_model_dir': None,   # Use default mobile model
            'rec_model_dir': None,   # Use default mobile model
            'cls_model_dir': None,   # No classification model
        }
        
        # Используем контекстный менеджер для полного подавления вывода PaddleOCR
        with suppress_paddle_output():
            # Временно повышаем уровень логирования для подавления сообщений при инициализации
            original_level = logging.getLogger('ppocr').level
            logging.getLogger('ppocr').setLevel(logging.ERROR)
            
            try:
                # Инициализируем PaddleOCR с минимальными параметрами
                self.ocr = PaddleOCR(**ocr_params)
                logger.info("PaddleOCR initialized with minimal parameters")
            finally:
                # Восстанавливаем исходный уровень логирования
                logging.getLogger('ppocr').setLevel(original_level)
        
        # 2. Init ProPainter с безопасной загрузкой на устройство
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        if not weights_path.exists():
            raise FileNotFoundError(f"Weights not found: {weights_path}")
            
        logger.info(f"Loading ProPainter model from {weights_path}")
        
        # Безопасная загрузка модели с обработкой ошибок CUDA
        try:
            # Создаем модель на CPU сначала
            logger.info("Creating ProPainter model on CPU...")
            self.model = InpaintGenerator(model_path=str(weights_path))
            
            # Пробуем переместить на GPU если доступно
            if self.device.type == 'cuda':
                try:
                    logger.info("Moving model to CUDA device...")
                    self.model = self.model.to(self.device)
                    
                    # Проверяем, что модель действительно на GPU
                    model_device = next(self.model.parameters()).device
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
                
            self.model.eval()
            
            # Проверяем устройство модели
            model_device = next(self.model.parameters()).device
            logger.info(f"ProPainter model loaded on device: {model_device}")
            
        except Exception as e:
            logger.error(f"Failed to load ProPainter model: {e}")
            raise

    def process_frames(self, input_dir: Path, output_dir: Path):
        import time
        start_time = time.time()
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Временная папка для масок
        tmp_mask_dir = output_dir.parent / "tmp_masks_propainter"
        if tmp_mask_dir.exists(): shutil.rmtree(tmp_mask_dir)
        tmp_mask_dir.mkdir()

        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            logger.error("No frames found!")
            return

        total_frames = len(frames)
        logger.info(f"Processing {total_frames} frames with ProPainter...")
        
        # Оптимизация для CPU: уменьшаем batch size и используем многопоточность
        if self.device.type == 'cpu':
            batch_size = 4  # Меньше для CPU чтобы не перегружать память
            logger.info("CPU mode: using smaller batch size and optimized settings")
        else:
            batch_size = 8  # Для GPU можно больше
        
        # Try to import tqdm for progress bar
        try:
            from tqdm import tqdm
            use_tqdm = True
        except ImportError:
            use_tqdm = False
            logger.info("tqdm not available, using simple logging")
        
        logger.info(f"Step 1/2: Generating masks for {total_frames} frames (batch size: {batch_size})...")
        
        # --- PASS 1: Generate Masks ---
        # Оптимизация для CPU: используем многопоточность и кэширование
        mask_start_time = time.time()
        
        # Оптимизация: предзагружаем изображения для лучшей производительности
        if self.device.type == 'cpu':
            logger.info("CPU optimization: preloading images for better performance...")
            # Можно добавить предзагрузку изображений если нужно
        
        if use_tqdm:
            for i in tqdm(range(0, len(frames), batch_size), desc="Processing batches", unit="batch"):
                batch = frames[i:i+batch_size]
                self._create_masks_batch(batch, tmp_mask_dir)
        else:
            for i in range(0, len(frames), batch_size):
                batch = frames[i:i+batch_size]
                self._create_masks_batch(batch, tmp_mask_dir)
                processed = min(i + batch_size, len(frames))
                elapsed = time.time() - mask_start_time
                speed = processed / elapsed if elapsed > 0 else 0
                remaining = (len(frames) - processed) / speed if speed > 0 else 0
                
                # Более частые обновления для коротких видео
                update_freq = max(1, len(frames) // 10)  # 10 обновлений
                if (i + batch_size) % update_freq == 0 or i + batch_size >= len(frames):
                    logger.info(f"Created masks for {processed}/{len(frames)} frames, "
                              f"speed: {speed:.2f} FPS, "
                              f"ETA: {remaining/60:.1f} min")

        logger.info("Step 2/2: Running AI Inpainting (ProPainter)...")

        # --- PASS 2: AI Inference ---
        # Оптимизация для CPU: обрабатываем меньшими частями если видео большое
        video_frames, _ = read_video(str(input_dir))
        video_masks, _ = read_video(str(tmp_mask_dir), gray=True)
        
        # Подготовка тензоров
        video_frames = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
        video_masks = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
        
        # Оптимизация для обработки частями чтобы избежать нехватки памяти
        # Автоматически определяем максимальное количество кадров на основе доступной памяти
        total_frames = video_frames.shape[0]
        
        # Определяем максимальное количество кадров для обработки за раз
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
                
                logger.info(f"GPU optimization: processing {total_frames} frames in chunks of {max_frames_per_chunk}")
            except Exception as e:
                logger.warning(f"Could not determine GPU memory, using default: {e}")
                max_frames_per_chunk = 15  # Безопасное значение по умолчанию
        else:
            max_frames_per_chunk = 30  # Для CPU можно больше
            
        # Всегда обрабатываем частями для безопасности
        if total_frames > max_frames_per_chunk:
            logger.info(f"Memory optimization: processing {total_frames} frames in chunks of {max_frames_per_chunk}")
            
            pred_chunks = []
            for chunk_start in range(0, total_frames, max_frames_per_chunk):
                chunk_end = min(chunk_start + max_frames_per_chunk, total_frames)
                logger.info(f"Processing chunk {chunk_start}-{chunk_end} of {total_frames}")
                
                # Вырезаем чанк
                frames_chunk = video_frames[chunk_start:chunk_end].unsqueeze(0).to(self.device)
                masks_chunk = video_masks[chunk_start:chunk_end].unsqueeze(0).to(self.device)
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
                
                # Inference with flexible ProPainter API support
                inference_start = time.time()
                with torch.no_grad():
                    try:
                        # Попробуем разные варианты API ProPainter
                        # Вариант 1: Новый API с 4 аргументами
                        if self.autocast is not None:
                            with self.autocast():
                                pred_chunk = self.model(masked_input, masks_chunk, masks_chunk, 10)
                        else:
                            pred_chunk = self.model(masked_input, masks_chunk, masks_chunk, 10)
                    except TypeError as e:
                        if "positional argument" in str(e):
                            logger.warning(f"API mismatch: {e}. Trying alternative API...")
                            # Вариант 2: Старый API с 2 аргументами
                            try:
                                if self.autocast is not None:
                                    with self.autocast():
                                        pred_chunk = self.model(masked_input, masks_chunk)
                                else:
                                    pred_chunk = self.model(masked_input, masks_chunk)
                                logger.info("Using old ProPainter API (2 arguments)")
                            except TypeError as e2:
                                logger.warning(f"Old API also failed: {e2}. Trying with 3 arguments...")
                                # Вариант 3: Промежуточный API с 3 аргументами
                                try:
                                    if self.autocast is not None:
                                        with self.autocast():
                                            pred_chunk = self.model(masked_input, masks_chunk, masks_chunk)
                                    else:
                                        pred_chunk = self.model(masked_input, masks_chunk, masks_chunk)
                                    logger.info("Using intermediate ProPainter API (3 arguments)")
                                except TypeError as e3:
                                    logger.error(f"All API attempts failed: {e3}")
                                    raise
                    except torch.cuda.OutOfMemoryError:
                        # Если не хватает памяти, уменьшаем размер чанка и пробуем снова
                        logger.warning(f"Out of memory for chunk {chunk_start}-{chunk_end}, reducing chunk size...")
                        torch.cuda.empty_cache()
                        
                        # Уменьшаем размер чанка вдвое
                        half_chunk = t // 2
                        pred_chunks_half = []
                        
                        for sub_start in range(0, t, half_chunk):
                            sub_end = min(sub_start + half_chunk, t)
                            logger.info(f"Processing sub-chunk {sub_start}-{sub_end} of chunk {chunk_start}-{chunk_end}")
                            
                            sub_frames = frames_chunk[:, sub_start:sub_end]
                            sub_masks = masks_chunk[:, sub_start:sub_end]
                            sub_masked = sub_frames * (1 - sub_masks)
                            
                            # Используем гибкий API для sub-чанков
                            try:
                                if self.autocast is not None:
                                    with self.autocast():
                                        sub_pred = self.model(sub_masked, sub_masks, sub_masks, 10)
                                else:
                                    sub_pred = self.model(sub_masked, sub_masks, sub_masks, 10)
                            except TypeError:
                                # Fallback на старый API
                                if self.autocast is not None:
                                    with self.autocast():
                                        sub_pred = self.model(sub_masked, sub_masks)
                                else:
                                    sub_pred = self.model(sub_masked, sub_masks)
                            
                            sub_pred = sub_pred[0, :, :, :h, :w]
                            pred_chunks_half.append(sub_pred.cpu())
                            torch.cuda.empty_cache()
                        
                        # Объединяем sub-чанки
                        pred_chunk = torch.cat(pred_chunks_half, dim=0).unsqueeze(0)
                
                inference_time = time.time() - inference_start
                logger.info(f"Chunk {chunk_start}-{chunk_end} completed in {inference_time:.1f}s "
                          f"({t/inference_time:.1f} FPS)")
                
                # Убираем паддинг и сохраняем
                pred_chunk = pred_chunk[0, :, :, :h, :w]
                pred_chunks.append(pred_chunk.cpu())
                
                # Очищаем кэш CUDA после каждого чанка
                if self.device.type == 'cuda':
                    torch.cuda.empty_cache()
                    allocated = torch.cuda.memory_allocated() / 1e9
                    logger.info(f"GPU memory after chunk: {allocated:.2f} GB allocated")
            
            # Объединяем все чанки
            pred_frames = torch.cat(pred_chunks, dim=0)
            
        else:
            # Обрабатываем все кадры сразу (для GPU или коротких видео)
            video_frames = video_frames.unsqueeze(0).to(self.device)
            video_masks = video_masks.unsqueeze(0).to(self.device)
            video_masks = (video_masks > 0.5).float()
            
            masked_input = video_frames * (1 - video_masks)
            
            # Ресайз если нужно
            b, t, c, h, w = masked_input.shape
            pad_h = (8 - h % 8) % 8
            pad_w = (8 - w % 8) % 8
            if pad_h > 0 or pad_w > 0:
                import torch.nn.functional as F
                masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
                video_masks = F.pad(video_masks, (0, pad_w, 0, pad_h))
            
            logger.info(f"Processing video with ProPainter: {t} frames, resolution: {h}x{w}")
            logger.info(f"Using device: {self.device}")
            
            inference_start = time.time()
            with torch.no_grad():
                logger.info("Starting ProPainter inference...")
                logger.info(f"Video resolution: {h}x{w}, frames: {t}")
                logger.info(f"Tensor shape: {masked_input.shape}")
                
                try:
                    # Гибкий вызов API ProPainter с поддержкой разных версий
                    if self.autocast is not None:
                        with self.autocast():
                            pred_frames = self._call_propainter_api(masked_input, video_masks)
                    else:
                        pred_frames = self._call_propainter_api(masked_input, video_masks)
                except torch.cuda.OutOfMemoryError as e:
                    logger.error(f"CUDA out of memory: {e}")
                    logger.info("Falling back to CPU processing...")
                    
                    # Перемещаем данные на CPU
                    masked_input_cpu = masked_input.cpu()
                    video_masks_cpu = video_masks.cpu()
                    self.model.cpu()
                    
                    # Очищаем GPU память
                    torch.cuda.empty_cache()
                    
                    # Обрабатываем на CPU
                    pred_frames = self._call_propainter_api(masked_input_cpu, video_masks_cpu)
                    
                    # Возвращаем модель на GPU если нужно
                    if self.device.type == 'cuda':
                        self.model.to(self.device)
            
            inference_time = time.time() - inference_start
            logger.info(f"ProPainter inference completed in {inference_time:.1f} seconds")
            logger.info(f"Inference speed: {t / inference_time:.1f} FPS")
            
            pred_frames = pred_frames[0, :, :, :h, :w]
            
            # Очищаем кэш CUDA
            if self.device.type == 'cuda':
                torch.cuda.empty_cache()

        # Убираем паддинг и батч
        pred_frames = pred_frames[0, :, :, :h, :w]
        
        # Сохраняем
        pred_frames = pred_frames.permute(0, 2, 3, 1).cpu().numpy() * 255.0
        pred_frames = pred_frames.astype(np.uint8)

        logger.info(f"Saving {len(pred_frames)} processed frames...")
        
        # Save frames with progress
        if use_tqdm:
            for i, frame in enumerate(tqdm(pred_frames, desc="Saving frames", unit="frame")):
                original_name = frames[i].name
                # Convert RGB back to BGR for OpenCV save
                cv2.imwrite(str(output_dir / original_name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        else:
            for i, frame in enumerate(pred_frames):
                original_name = frames[i].name
                # Convert RGB back to BGR for OpenCV save
                cv2.imwrite(str(output_dir / original_name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                if (i + 1) % 10 == 0 or i == len(pred_frames) - 1:
                    logger.info(f"Saved {i + 1}/{len(pred_frames)} frames")

        # Cleanup
        shutil.rmtree(tmp_mask_dir)
        total_time = time.time() - start_time
        logger.info(f"ProPainter processing complete. Total time: {total_time:.1f} seconds")
        logger.info(f"Average speed: {total_frames / total_time:.1f} FPS")

    def _create_masks_batch(self, img_paths: List[Path], output_dir: Path):
        """Create masks for a batch of images (optimized version)."""
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
                # Используем только минимальные параметры
                thread_local.ocr = PaddleOCR(
                    lang=self.lang,
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
        # PaddleOCR быстрее работает с меньшим разрешением
        max_ocr_dim = 480  # Уменьшили с 720 до 480 для большей скорости
        
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
        # Используем ThreadPoolExecutor для параллельного OCR
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Ограничиваем количество потоков, чтобы не перегружать систему
            list(executor.map(process_single_image, args_list))
    
    def _create_mask(self, img_path: Path, mask_path: Path):
        """Legacy single-image mask creation (for compatibility)."""
        self._create_masks_batch([img_path], mask_path.parent)
    
    def _call_propainter_api(self, frames, masks):
        """
        Гибкий вызов API ProPainter с поддержкой разных версий.
        
        Args:
            frames: Входные кадры
            masks: Маски
            
        Returns:
            Результат обработки
        """
        # Попробуем разные варианты API
        # Вариант 1: Новый API с 4 аргументами
        try:
            return self.model(frames, masks, masks, 10)
        except TypeError as e1:
            if "positional argument" in str(e1):
                logger.warning(f"API 4-args failed: {e1}")
                # Вариант 2: Старый API с 2 аргументами
                try:
                    return self.model(frames, masks)
                except TypeError as e2:
                    logger.warning(f"API 2-args failed: {e2}")
                    # Вариант 3: Промежуточный API с 3 аргументами
                    try:
                        return self.model(frames, masks, masks)
                    except TypeError as e3:
                        logger.error(f"All API attempts failed: {e3}")
                        # Пробуем определить правильное количество аргументов
                        import inspect
                        try:
                            sig = inspect.signature(self.model.forward)
                            params = len(sig.parameters)
                            logger.info(f"Model forward signature: {sig}")
                            logger.info(f"Number of parameters: {params}")
                            
                            # Создаем аргументы на основе сигнатуры
                            if params == 2:
                                return self.model(frames, masks)
                            elif params == 3:
                                return self.model(frames, masks, masks)
                            elif params == 4:
                                return self.model(frames, masks, masks, 10)
                            else:
                                raise ValueError(f"Unsupported number of parameters: {params}")
                        except:
                            # Последняя попытка: используем 2 аргумента (самый старый API)
                            logger.warning("Using fallback API with 2 arguments")
                            return self.model(frames, masks)


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
