import shutil
from pathlib import Path
from src.core.config import get_config
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.services.mask_service import MaskGeneratorService
from src.shared.logging import get_logger

logger = get_logger(__name__)

class StreamingSubtitleRemoverService:
    """
    Orchestrates the subtitle removal pipeline:
    Frames -> Mask Generation (OCR) -> Inpainting (ProPainter CLI) -> Output
    """
    
    def __init__(self, lang: str = None, use_gpu: bool = True, **kwargs):
        config = get_config()
        self.lang = lang or config.OCR_LANG
        self.use_gpu = use_gpu
        
        # Extract ROI from kwargs
        roi_str = kwargs.get('roi_str', None)
        if roi_str:
            logger.info(f"StreamingSubtitleRemoverService initialized with ROI: {roi_str}")

        # Services
        self.mask_service = MaskGeneratorService(lang=self.lang, use_gpu=self.use_gpu, roi_str=roi_str, **kwargs)
        self.inpainter = ProPainterAdapter() # Subprocess wrapper
        
    def process_frames_direct(self, frame_paths: list[Path], output_dir: Path):
        """
        Process a list of frames. Handles temp directory management.
        """
        # 1. Setup Temp Dirs
        work_dir = output_dir.parent / "tmp_work_processing"
        if work_dir.exists(): shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True)
        
        frames_dir = work_dir / "frames"
        masks_dir = work_dir / "masks"
        frames_dir.mkdir()
        masks_dir.mkdir()
        
        try:
            # 2. Stage Frames (Copy specific frames to temp dir)
            logger.info(f"Staging {len(frame_paths)} frames...")
            # Если frames меньше 5 (например, 1 картинка), дублируем их для ProPainter
            is_single_image = len(frame_paths) == 1
            
            if is_single_image:
                src = frame_paths[0]
                for i in range(5): # Fake video sequence
                    shutil.copy(src, frames_dir / f"{i:05d}.jpg")
            else:
                for i, src in enumerate(frame_paths):
                    shutil.copy(src, frames_dir / f"{i:05d}.jpg")

            # 3. Generate Masks
            self.mask_service.generate_masks(frames_dir, masks_dir)
            
            # 4. Inpaint (External Process)
            # Результат ProPainter положит в папку внутри work_dir, или мы укажем output
            # Адаптер вернет путь к папке с готовыми кадрами
            inpainted_frames_dir = self.inpainter.process(frames_dir, masks_dir, work_dir / "results")
            
            # 5. Retrieve Results
            output_dir.mkdir(parents=True, exist_ok=True)
            
            results = sorted(list(inpainted_frames_dir.glob("*.jpg")) + list(inpainted_frames_dir.glob("*.png")))
            
            if is_single_image:
                # Если была одна картинка, берем первый кадр результата и сохраняем с оригинальным именем
                shutil.copy(results[0], output_dir / frame_paths[0].name)
            else:
                # Копируем всё обратно, маппинг по именам
                for i, res_path in enumerate(results):
                    if i < len(frame_paths):
                        target_name = frame_paths[i].name
                        shutil.copy(res_path, output_dir / target_name)
                        
            logger.info(f"Processing complete. Results in {output_dir}")
            return True

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            return False
        finally:
            # Cleanup
            if work_dir.exists():
                shutil.rmtree(work_dir)
    
    def is_available(self) -> bool:
        """Check if subtitle remover is available (ProPainter + OCR)."""
        try:
            # Check OCR
            import paddleocr  # noqa: F401
            
            # Check ProPainter - try to create adapter
            # This is a simple check; actual availability would be determined
            # when process_frames_direct is called
            from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
            adapter = ProPainterAdapter()
            # If we can create the adapter without errors, assume it's available
            # (actual ProPainter availability would be checked when process is called)
            return True
            
        except ImportError:
            return False
