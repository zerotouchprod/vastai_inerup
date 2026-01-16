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

        # 3. Setup Environment (Fail Fast)
        if not (self.root / "inference_propainter.py").exists():
            logger.warning(f"⚠️ ProPainter not found at {self.root}")
        else:
            # Patch bugs and validate RAFT immediately
            self.env_manager.patch_propainter_misc(self.root)
            self.env_manager.validate_raft_availability()

    def process(self, input_path: Union[str, Path, List[Path]], mask_dir: Path, output_path: Path) -> Path:
        """
        Main entry point. Orchestrates the pipeline.
        """
        logger.info("🚀 Starting ProPainter Pipeline...")
        
        # 1. Setup GPU Environment (TF32, Visible Devices, etc.)
        gpu_info = self.env_manager.setup_gpu_environment()
        self.inference_runner.set_gpu_config(gpu_info)

        # 2. Prepare Input Media (Video -> Frames)
        # Handles video files, frame directories, or lists of paths
        frames_dir = self.media_processor.prepare_input(input_path)
        
        # 3. Analyze Resolution
        # Calculates VRAM-safe resolution based on hardware
        original_dims = self.media_processor.get_frame_dimensions(frames_dir)
        target_width, target_height = self.res_calculator.calculate_target_dimensions(
            original_dims[0], original_dims[1], gpu_info['total_vram_gb']
        )
        
        # 4. Generate Execution Strategy (Chunks)
        # Splits frames into overlapping chunks to fit in VRAM
        chunks = self.strategy.generate_chunks(frames_dir, mask_dir, output_path.parent)
        
        # 5. Execute Inference (Parallel or Sequential)
        # This delegate handles the complex subprocess calls and error handling
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
