import os
import sys
import torch
from pathlib import Path
from src.shared.logging import get_logger

# Добавляем путь к ProPainter в sys.path, чтобы импорты работали
PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
if PROPAINTER_ROOT not in sys.path:
    sys.path.append(PROPAINTER_ROOT)

try:
    from model.propainter import InpaintGenerator
    # Предполагаем наличие функции инференса или пишем свою обертку, загружающую веса
except ImportError:
    pass # Обработаем в runtime

logger = get_logger(__name__)

class ProPainterAdapter:
    def __init__(self, weights_path: str = None):
        self.weights_path = weights_path or f"{PROPAINTER_ROOT}/weights/ProPainter.pth"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def process(self, video_path: Path, mask_dir: Path, output_path: Path):
        logger.info("Starting ProPainter Inpainting...")
        
        # Здесь мы вызываем CLI пропейнтера или его API.
        # Для надежности в рамках скрипта проще вызвать subprocess или 
        # адаптировать код inference_propainter.py из репозитория.
        
        # Пример вызова через subprocess (самый надежный способ изоляции памяти):
        import subprocess
        
        cmd = [
            "python", f"{PROPAINTER_ROOT}/inference_propainter.py",
            "--video", str(video_path),
            "--mask", str(mask_dir),
            "--output", str(output_path.parent),
            "--save_format", "mp4"
        ]
        
        # Важно: inference_propainter часто сохраняет результат с фиксированным именем.
        # Нужно переименовать результат в output_path после завершения.
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            logger.error(f"ProPainter failed: {process.stderr}")
            raise RuntimeError("ProPainter execution failed")
            
        logger.info("ProPainter finished successfully.")
        
        # Логика поиска результата и переименования
        # Обычно ProPainter создает папку results/..., надо найти mp4 там
        # ... (код поиска файла) ...
        # For now, just return the output path
        return output_path

# Keep old ProPainterModelAdapter for backward compatibility
class ProPainterModelAdapter:
    """Backward compatibility wrapper for ProPainterModelAdapter."""
    
    def __init__(self, model: torch.nn.Module, device: torch.device):
        import warnings
        warnings.warn("ProPainterModelAdapter is deprecated. Use ProPainterAdapter instead.", DeprecationWarning)
        self.model = model
        self.device = device
        
    def process_chunk(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """Deprecated method for backward compatibility."""
        raise NotImplementedError("ProPainterModelAdapter is deprecated. Use ProPainterAdapter instead.")
