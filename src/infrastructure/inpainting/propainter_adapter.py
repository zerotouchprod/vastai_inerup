import os
import shutil
from pathlib import Path
from typing import List, Union

from src.shared.logging import get_logger
from src.core.config import get_config

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
        self.root = Path(propainter_root or self.config.PROPAINTER_ROOT)
        
        # 2. Initialize Components
        self.env_manager = EnvironmentManager(self.config)
        self.media_processor = MediaProcessor(self.config)
        self.res_calculator = ResolutionCalculator(self.config)
        self.strategy = SlidingWindowStrategy(self.config)
        
        # InferenceRunner needs root path to find scripts
        self.inference_runner = InferenceRunner(self.config, self.root)
        
        # Set logger for environment manager
        self.env_manager.logger = logger
        
        # Backward compatibility aliases
        self.resolution_calculator = self.res_calculator
        self.environment_manager = self.env_manager
        self.media_processor = self.media_processor  # already same

        # 3. Setup Environment (Fail Fast)
        if not (self.root / "inference_propainter.py").exists():
            logger.warning(f"⚠️ ProPainter not found at {self.root}")
        else:
            # Patch bugs and validate RAFT immediately
            self.env_manager.patch_propainter_misc(self.root)
            self.env_manager.validate_raft_availability()
        
        # 4. Setup AMP environment if enabled
        if self.config.USE_AMP:
            self.env_manager.setup_amp_environment()
        
        # Backward compatibility attributes
        self.CHUNK_SIZE = self.config.MAX_FRAMES_PER_CHUNK
        self.OVERLAP = self.config.PROPAINTER_OVERLAP

    def process(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Main entry point. Orchestrates the pipeline.
        """
        logger.info("🚀 Starting ProPainter Pipeline with SMART ADAPTATION...")
        
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

# ==============================================================================
# DEPRECATED CLASSES (Keep for backward compatibility if needed)
# ==============================================================================

class ProPainterModelAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Use ProPainterAdapter instead.")
