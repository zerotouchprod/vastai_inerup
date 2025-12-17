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

from domain.models import ProcessingResult

# Обеспечиваем доступ к модулям ProPainter
PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
if PROPAINTER_ROOT not in sys.path:
    sys.path.append(PROPAINTER_ROOT)

try:
    # Импорты из репозитория ProPainter
    from model.propainter import InpaintGenerator
    from utils.video_utils import read_video
except ImportError:
    logging.warning("⚠️ ProPainter modules not found! Make sure they are in /opt/ProPainter")

try:
    from paddleocr import PaddleOCR
except ImportError:
    pass

logger = logging.getLogger(__name__)

class SubtitleRemoverProPainter:
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        """
        :param mask_dilation: Насколько расширять маску. 
                              Для ProPainter лучше брать больше (10-15), 
                              чтобы он перерисовал весь ореол субтитров.
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.lang = lang
        self.mask_dilation = mask_dilation
        
        logger.info(f"Initializing ProPainter Subtitle Remover (lang={lang}, dilation={mask_dilation})")

        # 1. Init OCR (CPU is enough)
        self.ocr = PaddleOCR(use_angle_cls=False, lang=lang, use_gpu=False, show_log=False)
        
        # 2. Init ProPainter
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        if not weights_path.exists():
            raise FileNotFoundError(f"Weights not found: {weights_path}")
            
        self.model = InpaintGenerator(model_path=str(weights_path)).to(self.device)
        self.model.eval()

    def process_frames(self, input_dir: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Временная папка для масок
        tmp_mask_dir = output_dir.parent / "tmp_masks_propainter"
        if tmp_mask_dir.exists(): shutil.rmtree(tmp_mask_dir)
        tmp_mask_dir.mkdir()

        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames:
            logger.error("No frames found!")
            return

        logger.info(f"Step 1/2: Generating masks for {len(frames)} frames...")
        
        # --- PASS 1: Generate Masks ---
        for img_path in frames:
            self._create_mask(img_path, tmp_mask_dir / img_path.name)

        logger.info("Step 2/2: Running AI Inpainting (ProPainter)...")

        # --- PASS 2: AI Inference ---
        # Читаем видео и маски в память (ProPainter утилита)
        # masked_frames: [T, H, W, 3] (RGB 0-255)
        video_frames, _ = read_video(str(input_dir))
        video_masks, _ = read_video(str(tmp_mask_dir), gray=True)
        
        # Подготовка тензоров
        # [T, H, W, C] -> [T, C, H, W] -> Normalize 0-1
        video_frames = torch.from_numpy(video_frames).permute(0, 3, 1, 2).float() / 255.0
        video_masks = torch.from_numpy(video_masks).permute(0, 3, 1, 2).float() / 255.0
        
        # Add Batch Dimension [1, T, C, H, W]
        video_frames = video_frames.unsqueeze(0).to(self.device)
        video_masks = video_masks.unsqueeze(0).to(self.device)
        
        # Бинаризация маски (на всякий случай)
        video_masks = (video_masks > 0.5).float()
        
        # Создаем входное видео с "дырками"
        masked_input = video_frames * (1 - video_masks)

        # Ресайз если нужно (ProPainter любит кратность 8)
        b, t, c, h, w = masked_input.shape
        pad_h = (8 - h % 8) % 8
        pad_w = (8 - w % 8) % 8
        if pad_h > 0 or pad_w > 0:
            import torch.nn.functional as F
            masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
            video_masks = F.pad(video_masks, (0, pad_w, 0, pad_h))

        with torch.no_grad():
            # Pred output: [1, T, 3, H, W]
            pred_frames = self.model(masked_input, video_masks)

        # Убираем паддинг и батч
        pred_frames = pred_frames[0, :, :, :h, :w]
        
        # Сохраняем
        pred_frames = pred_frames.permute(0, 2, 3, 1).cpu().numpy() * 255.0
        pred_frames = pred_frames.astype(np.uint8)

        for i, frame in enumerate(pred_frames):
            original_name = frames[i].name
            # Convert RGB back to BGR for OpenCV save
            cv2.imwrite(str(output_dir / original_name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

        # Cleanup
        shutil.rmtree(tmp_mask_dir)
        logger.info("ProPainter processing complete.")

    def _create_mask(self, img_path: Path, mask_path: Path):
        img = cv2.imread(str(img_path))
        if img is None: return
        
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        result = self.ocr.ocr(img, cls=False)
        if result and result[0]:
            for line in result[0]:
                coords = line[0]
                conf = line[1][1]
                # Ловим даже неуверенный текст, чтобы ProPainter его затер
                if conf > 0.4: 
                    pts = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.fillPoly(mask, [pts], 255)
        
        # Агрессивное расширение для Glow
        if self.mask_dilation > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
            mask = cv2.dilate(mask, kernel, iterations=1)
            
        cv2.imwrite(str(mask_path), mask)


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
                from utils.video_utils import read_video
                
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
