import os
import shutil
import cv2
import numpy as np
from pathlib import Path
from typing import List, Union, Optional

from src.shared.logging import get_logger
from src.core.config import get_config
from src.core.exceptions import ProcessorNotAvailableError
from src.schemas.roi import InpaintConfig
from src.infrastructure.image_processing.geometry import (
    get_roi_from_mask, crop_frame, paste_frame, dilate_mask
)

# Import components
from src.infrastructure.inpainting.components.resolution import ResolutionCalculator
from src.infrastructure.inpainting.components.strategy import SlidingWindowStrategy
from src.infrastructure.inpainting.components.inference import InferenceRunner
from src.infrastructure.inpainting.components.environment import EnvironmentManager
from src.infrastructure.inpainting.components.media import MediaProcessor

logger = get_logger(__name__)

class ProPainterAdapter:
    """
    Facade for ProPainter inference pipeline.
    Delegates logic to specialized components (SRP).
    """
    
    def __init__(self, propainter_root: str = None):
        # 1. Config & Paths
        self.config = get_config()
        # Use provided root, or computed PROPAINTER_DIR, or default PROPAINTER_ROOT
        propainter_dir = self.config.PROPAINTER_DIR
        default_root = propainter_dir if propainter_dir is not None else self.config.PROPAINTER_ROOT
        self.root = Path(propainter_root or default_root)
        
        # 2. ROI configuration (must be before component initialization)
        self.roi_config = InpaintConfig(
            method='propainter',
            padding_px=self.config.PADDING_PX,
            use_roi_optimization=self.config.USE_ROI_OPTIMIZATION,
            fallback_to_cv2=True,
            preserve_background=True,
            force_binary_mask=True,
            mask_dilation=self.config.MASK_DILATION,
            use_half_precision=self.config.USE_AMP
        )
        
        # 3. Initialize Components
        self.env_manager = EnvironmentManager(self.config)
        self.media_processor = MediaProcessor(self.config)
        self.res_calculator = ResolutionCalculator(self.config)
        self.strategy = SlidingWindowStrategy(self.config)
        
        # InferenceRunner needs root path to find scripts
        self.inference_runner = InferenceRunner(self.config, self.root)
        self.inference_runner.set_inpaint_config(self.roi_config)
        
        # Set logger for environment manager
        self.env_manager.logger = logger
        
        # Backward compatibility aliases
        self.resolution_calculator = self.res_calculator
        self.environment_manager = self.env_manager
        self.media_processor = self.media_processor  # already same

        # 4. Setup Environment (Fail Fast)
        # Check if inference script exists
        inference_script = self.config.INFERENCE_SCRIPT
        if inference_script is None or not inference_script.exists():
            raise ProcessorNotAvailableError(
                f"ProPainter inference script not found. "
                f"Checked paths: {self.config.PROPAINTER_DIR}, inference_core.py"
            )
        
        logger.info(f"✅ ProPainter found at {self.root}, using script: {inference_script}")
        
        # Patch bugs and validate RAFT immediately
        self.env_manager.patch_propainter_misc(self.root)
        self.env_manager.validate_raft_availability()
        
        # 5. Setup AMP environment if enabled
        if self.config.USE_AMP:
            self.env_manager.setup_amp_environment()
        
        # Backward compatibility attributes
        self.CHUNK_SIZE = self.config.MAX_FRAMES_PER_CHUNK
        self.OVERLAP = self.config.PROPAINTER_OVERLAP

    def process(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Main entry point. Orchestrates the pipeline with OOM fallback.
        """
        logger.info("🚀 Starting ProPainter Pipeline with SMART ADAPTATION and OOM fallback...")
        
        try:
            return self._process_propainter(input_path, mask_dir, output_path)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() or "OOM" in str(e).upper():
                logger.warning(f"ProPainter OOM detected: {e}. Attempting fallback to ROI optimization...")
                return self._process_with_roi_fallback(input_path, mask_dir, output_path)
            else:
                # Re-raise if not OOM
                raise
    
    def _process_propainter(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Original ProPainter processing pipeline.
        """
        # 1. Setup GPU Environment (TF32, Visible Devices, etc.)
        gpu_info = self.env_manager.setup_gpu_environment()
        self.inference_runner.set_gpu_config(gpu_info)

        # 2. Prepare Input Media (Video -> Frames)
        # Handles video files, frame directories, or lists of paths
        frames_dir = self.media_processor.prepare_input(input_path)
        
        # 3. SMART CALCULATION: Resolution + Chunk Size
        original_dims = self.media_processor.get_frame_dimensions(frames_dir)
        
        # Используем новый метод, который возвращает всё сразу
        target_width, target_height, safe_chunk_size = self.res_calculator.calculate_optimal_params(
            original_dims[0], original_dims[1], gpu_info['total_vram_gb']
        )
        
        # ВАЖНО: Обновляем стратегию нарезки динамически!
        logger.info(f"🎯 Dynamic Settings applied: {target_width}x{target_height} @ {safe_chunk_size} frames/chunk")
        self.strategy.chunk_size = safe_chunk_size  # Переопределяем значение из конфига
        self.strategy.overlap = min(2, safe_chunk_size // 3) # Адаптивный нахлест (не больше 1/3 чанка)
        
        # 4. Generate Execution Strategy
        chunks = self.strategy.generate_chunks(frames_dir, mask_dir, output_path.parent)
        
        # 5. Execute Inference
        chunk_results = self.inference_runner.process_chunks(
            chunks, 
            width=target_width, 
            height=target_height
        )
        
        # 6. Finalize (Merge & Restore)
        # Merges chunks and restores original aspect ratio/resolution
        final_output = self.media_processor.merge_chunks(chunk_results, output_path)
        self.media_processor.restore_aspect_ratio(final_output, original_dims)
        
        # Cleanup temp files
        self.media_processor.cleanup(frames_dir)
        
        logger.info(f"✅ ProPainter pipeline completed: {final_output}")
        return final_output
    
    def _process_with_roi_fallback(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Fallback processing using ROI optimization to reduce VRAM usage.
        Processes each frame individually with LaMa + ROI or OpenCV fallback.
        """
        logger.info("🔄 Using ROI optimization fallback for OOM recovery...")
        
        # Import LaMa adapter lazily to avoid circular imports
        from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
        
        # Initialize LaMa adapter
        lama_adapter = LaMaAdapter()
        
        # Prepare frames directory
        frames_dir = self.media_processor.prepare_input(input_path)
        original_dims = self.media_processor.get_frame_dimensions(frames_dir)
        
        # Create output directory for processed frames
        output_frames_dir = output_path.parent / "roi_fallback_frames"
        output_frames_dir.mkdir(parents=True, exist_ok=True)
        
        # Get frame and mask files
        frame_files = sorted(frames_dir.glob("*.png"))
        mask_files = sorted(mask_dir.glob("*.png"))
        
        if len(frame_files) != len(mask_files):
            logger.error(f"Frame/Mask count mismatch: {len(frame_files)} != {len(mask_files)}")
            raise RuntimeError("Frame and mask count mismatch")
        
        # Process each frame individually
        processed_count = 0
        total_frames = len(frame_files)
        
        for i, (frame_file, mask_file) in enumerate(zip(frame_files, mask_files)):
            # Load frame and mask
            frame = cv2.imread(str(frame_file))
            mask = cv2.imread(str(mask_file), cv2.IMREAD_GRAYSCALE)
            
            if frame is None or mask is None:
                logger.warning(f"Failed to load {frame_file} or {mask_file}, skipping")
                continue
            
            try:
                # Use LaMa with ROI optimization
                inpainted = lama_adapter.process_with_roi(
                    frame, mask, config=self.roi_config
                )
                
                # Save result
                output_file = output_frames_dir / frame_file.name
                cv2.imwrite(str(output_file), inpainted)
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process frame {frame_file.name}: {e}")
                # Fallback to OpenCV inpainting
                mask_uint8 = (mask > 0).astype(np.uint8) * 255
                inpainted = cv2.inpaint(frame, mask_uint8, 3, cv2.INPAINT_TELEA)
                output_file = output_frames_dir / frame_file.name
                cv2.imwrite(str(output_file), inpainted)
                processed_count += 1
            
            if (i + 1) % 10 == 0:
                logger.info(f"Processed {i + 1}/{total_frames} frames with ROI fallback")
        
        logger.info(f"✅ ROI fallback completed: {processed_count}/{total_frames} frames processed")
        
        # Merge frames into video
        final_output = self.media_processor.merge_chunks(
            {f.name: f for f in output_frames_dir.iterdir()}, 
            output_path
        )
        self.media_processor.restore_aspect_ratio(final_output, original_dims)
        
        # Cleanup
        self.media_processor.cleanup(frames_dir)
        shutil.rmtree(output_frames_dir, ignore_errors=True)
        
        logger.info(f"✅ ROI fallback pipeline completed: {final_output}")
        return final_output

# ==============================================================================
# DEPRECATED CLASSES (Keep for backward compatibility if needed)
# ==============================================================================

class ProPainterModelAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Use ProPainterAdapter instead.")
