import tempfile
from pathlib import Path
from src.shared.logging import get_logger

logger = get_logger(__name__)

class SubtitleRemoverService:
    def __init__(self, mask_service, inpainter, roi="bottom"):
        self.mask_service = mask_service
        self.inpainter = inpainter
        self.roi = roi

    def process(self, input_path: Path, output_path: Path, **kwargs):
        """
        Метод, который вызывает Orchestrator.
        """
        logger.info(f"Removing subtitles from {input_path}")
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mask_dir = temp_path / "masks"
            
            # 1. Генерация масок (OCR + SAM2)
            self.mask_service.create_video_masks(input_path, mask_dir, roi=self.roi)
            
            # 2. Inpainting (ProPainter)
            # ProPainter сам сохранит видео. Нужно проконтролировать путь.
            self.inpainter.process(input_path, mask_dir, output_path)
            
        return output_path

# Keep old SubtitleRemoverService for backward compatibility
class LegacySubtitleRemoverService:
    """Backward compatibility wrapper for old SubtitleRemoverService."""
    
    def __init__(self,
                 lang: str = 'en',
                 mask_dilation: int = 15,
                 use_gpu: bool = True,
                 use_gpu_for_ocr: bool = False,
                 confidence_threshold: float = 0.1):
        import warnings
        warnings.warn("LegacySubtitleRemoverService is deprecated. Use SubtitleRemoverService with SAM2 pipeline instead.", DeprecationWarning)
        
        # Keep old initialization for backward compatibility
        from src.core.config import get_config
        from src.core.device import get_device_manager
        from src.services.mask_service import MaskGeneratorService
        from src.infrastructure.inpainting.propainter_loader import ProPainterLoader
        from src.infrastructure.inpainting.propainter_adapter import ProPainterModelAdapter
        
        config = get_config()
        
        self.lang = lang or config.OCR_LANG
        self.mask_dilation = mask_dilation or config.MASK_DILATION
        self.use_gpu = use_gpu if use_gpu is not None else config.USE_GPU
        self.use_gpu_for_ocr = use_gpu_for_ocr if use_gpu_for_ocr is not None else config.USE_GPU_FOR_OCR
        self.confidence_threshold = confidence_threshold or config.CONFIDENCE_THRESHOLD
        
        # Initialize device manager
        force_cpu = not self.use_gpu
        self.device_manager = get_device_manager(force_cpu=force_cpu)
        self.device = self.device_manager.get_device()
        
        # Initialize services
        self.mask_service = MaskGeneratorService(
            lang=self.lang,
            mask_dilation=self.mask_dilation,
            use_gpu_for_ocr=self.use_gpu_for_ocr,
            confidence_threshold=self.confidence_threshold
        )
        
        # Initialize ProPainter components
        self.propainter_loader = ProPainterLoader()
        self.model_adapter = None
        self.model_loaded = False
        
        logger.info(f"LegacySubtitleRemoverService initialized (lang={self.lang}, dilation={self.mask_dilation})")
    
    def process(self, request):
        """Deprecated process method."""
        raise NotImplementedError("LegacySubtitleRemoverService is deprecated. Use SubtitleRemoverService with SAM2 pipeline instead.")
