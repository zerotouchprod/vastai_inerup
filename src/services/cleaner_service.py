import tempfile
import shutil
import cv2
import numpy as np
from pathlib import Path
from src.shared.logging import get_logger

logger = get_logger(__name__)

class SubtitleRemoverService:
    def __init__(self, mask_service, inpainter, roi="bottom"):
        # ROI parameter is ignored - always use full-frame processing
        # mask_service parameter is also ignored - we generate our own binary masks
        self.inpainter = inpainter
        logger.info(f"SubtitleRemoverService initialized (ignoring ROI parameter, using full-frame processing)")

    def process(self, input_path, output_path: Path, **kwargs):
        """
        Метод, который вызывает Orchestrator.
        """
        logger.info(f"Removing subtitles from {input_path}")
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                mask_dir = temp_path / "masks"
                mask_dir.mkdir()
                
                # Handle list of frame paths
                if isinstance(input_path, list):
                    # Convert list of frames to directory
                    frames_dir = temp_path / "input_frames"
                    frames_dir.mkdir()
                    for i, frame_path in enumerate(input_path):
                        if isinstance(frame_path, Path):
                            shutil.copy(frame_path, frames_dir / f"frame_{i:06d}{frame_path.suffix}")
                        else:
                            shutil.copy(Path(frame_path), frames_dir / f"frame_{i:06d}{Path(frame_path).suffix}")
                    
                    # Generate binary masks for frames
                    self._generate_binary_masks(frames_dir, mask_dir)
                    
                    # Pass frames directory to inpainter
                    result_path = self.inpainter.process(frames_dir, mask_dir, output_path)
                else:
                    # Original video file or frames directory
                    input_path = Path(input_path)
                    
                    if input_path.is_dir():
                        # Frames directory
                        frames_dir = input_path
                        # Generate binary masks for frames
                        self._generate_binary_masks(frames_dir, mask_dir)
                        
                        # Pass frames directory to inpainter
                        result_path = self.inpainter.process(frames_dir, mask_dir, output_path)
                    else:
                        # Video file - extract frames first
                        from src.infrastructure.media.ffmpeg import FFmpegExtractor
                        extractor = FFmpegExtractor()
                        frames_dir = temp_path / "extracted_frames"
                        frames_dir.mkdir()
                        
                        logger.info(f"Extracting frames from video: {input_path}")
                        extractor.extract_frames(input_path, frames_dir)
                        
                        # Generate binary masks for frames
                        self._generate_binary_masks(frames_dir, mask_dir)
                        
                        # Pass frames directory to inpainter
                        result_path = self.inpainter.process(frames_dir, mask_dir, output_path)
                
            # Return a result object that the orchestrator expects
            class SimpleResult:
                def __init__(self, success=True, output_path=None):
                    self.success = success
                    self.output_path = output_path
            
            return SimpleResult(success=True, output_path=result_path)
            
        except Exception as e:
            logger.error(f"Subtitle removal failed: {e}")
            # Return failure result
            class SimpleResult:
                def __init__(self, success=False, output_path=None, errors=None):
                    self.success = success
                    self.output_path = output_path
                    self.errors = [str(e)] if errors is None else errors
            
            return SimpleResult(success=False, output_path=None, errors=[str(e)])

    def _generate_binary_masks(self, frames_dir: Path, mask_dir: Path):
        """
        Generate binary masks (black background with white filled polygons) for all frames.
        This replaces the old mask service that created green overlays and applied ROI cropping.
        
        Updated parameters:
        - confidence_threshold: 0.2 -> 0.35 (reduce false positives - don't detect eyes/hair as text)
        - kernel: (10, 10) -> (15, 15) (more aggressive dilation to cover text shadows/outlines)
        - iterations: 2 (maintained) for thorough dilation
        """
        logger.info(f"Generating binary masks for frames in {frames_dir}")
        
        # Get OCR service
        from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
        ocr = PaddleWrapper(lang='en', use_gpu=True)
        
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")
        
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None:
                logger.warning(f"Failed to read frame: {frame_path}")
                continue
            
            # Get image dimensions
            h, w = img.shape[:2]
            
            # OCR detection with higher confidence threshold to reduce false positives
            # 0.35 instead of 0.2 to avoid detecting eyes/hair as text
            bboxes = ocr.detect(img, confidence_threshold=0.35)
            
            # Create black background (1 channel)
            mask = np.zeros((h, w), dtype=np.uint8)
            
            for bbox in bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                # Draw white polygon on mask
                cv2.fillPoly(mask, [points], 255)
            
            # Apply more aggressive dilation to ensure text shadows/outlines are fully covered
            # Prevents "purple soap" effect where leftover pixels get smeared
            if len(bboxes) > 0:
                kernel = np.ones((15, 15), np.uint8)  # Larger kernel for more dilation
                mask = cv2.dilate(mask, kernel, iterations=2)  # Two iterations for thorough coverage
            
            # Save mask with same name as frame (but .png extension)
            mask_name = f"{frame_path.stem}.png"
            cv2.imwrite(str(mask_dir / mask_name), mask)
        
        logger.info(f"Generated {len(frames)} binary masks in {mask_dir}")

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
        
        # Initialize ProPainter components (deprecated - will fail if used)
        self.propainter_loader = None
        self.model_adapter = None
        self.model_loaded = False
        
        logger.info(f"LegacySubtitleRemoverService initialized (lang={self.lang}, dilation={self.mask_dilation})")
        logger.warning("ProPainterLoader is deprecated. This service may not work properly.")
    
    def process(self, request):
        """Deprecated process method."""
        raise NotImplementedError("LegacySubtitleRemoverService is deprecated. Use SubtitleRemoverService with SAM2 pipeline instead.")
