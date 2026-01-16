import math
from typing import Tuple
from src.shared.logging import get_logger
from src.core.config import AppConfig

logger = get_logger(__name__)

class ResolutionCalculator:
    def __init__(self, config: AppConfig):
        self.config = config

    def calculate_optimal_params(self, 
                               original_width: int, 
                               original_height: int, 
                               vram_gb: float) -> Tuple[int, int, int]:
        """
        Calculates safe resolution AND chunk size based on available VRAM.
        
        Formula based on ProPainter benchmarks:
        Memory ~= (Width * Height * ChunkSize^2) * Constant
        
        Returns:
            (target_width, target_height, optimal_chunk_size)
        """
        # 1. Base constraints
        # RAFT requires decent VRAM. ProPainter overhead is ~2GB static + dynamic.
        usable_vram = max(0, vram_gb - 2.0)  # Reserve 2.0GB for system/torch overhead
        
        # Pixels in millions
        original_mp = (original_width * original_height) / 1_000_000
        
        # Heuristic constant derived from RTX 3090/4090 tests
        # 1080p (2MP) * 5 frames needs ~6GB
        # 1080p (2MP) * 10 frames needs ~14GB
        # This is an approximation, we play it slightly safe.
        
        # Calculate max frames fits in memory for ORIGINAL resolution
        # Memory ≈ MP * Frames * 0.5 (Empirical factor for FP32/TF32)
        # Frames ≈ UsableVRAM / (MP * 0.5)
        
        if original_mp <= 0: original_mp = 0.1 # Safety div by zero
        
        max_safe_frames_at_native = int(usable_vram / (original_mp * 0.5))
        
        # Clamp limits
        MIN_FRAMES = 4   # Minimum needed for temporal consistency
        MAX_FRAMES = 15  # Diminishing returns after this, and high risk
        
        target_width = original_width
        target_height = original_height
        final_chunk = max_safe_frames_at_native
        
        logger.info(f"🧮 VRAM Analysis: {vram_gb:.1f}GB total, {usable_vram:.1f}GB usable.")
        logger.info(f"   Native Res: {original_width}x{original_height} ({original_mp:.2f} MP).")
        logger.info(f"   Theoretical max frames at native: {max_safe_frames_at_native}")

        # --- SCENARIO 1: Native resolution fits (with at least MIN_FRAMES) ---
        if max_safe_frames_at_native >= MIN_FRAMES:
            # Cap at global max
            final_chunk = min(max_safe_frames_at_native, self.config.MAX_FRAMES_PER_CHUNK)
            logger.info(f"✅ Keeping native resolution. Adjusted chunk size to {final_chunk}.")
            
        # --- SCENARIO 2: Native is too big (OOM risk) -> Downscale ---
        else:
            logger.warning(f"⚠️ Native resolution too heavy for {vram_gb:.1f}GB VRAM (can only fit {max_safe_frames_at_native} frames).")
            
            # We fix chunk size to MIN_FRAMES and calculate max resolution
            # MP = UsableVRAM / (Frames * 0.5)
            target_mp = usable_vram / (MIN_FRAMES * 0.5)
            
            # Scale factor
            scale = math.sqrt(target_mp / original_mp)
            target_width = int(original_width * scale)
            target_height = int(original_height * scale)
            final_chunk = MIN_FRAMES
            
            logger.warning(f"   📉 Downscaling to {target_width}x{target_height} to keep {MIN_FRAMES} frames.")

        # --- FINAL ADJUSTMENTS ---
        # 1. Ensure Divisible by 32 (Requirement for RAFT/ProPainter)
        target_width = (target_width // 32) * 32
        target_height = (target_height // 32) * 32
        
        # Ensure minimal dimensions
        target_width = max(target_width, 128)
        target_height = max(target_height, 128)
        
        # 2. Apply MAX_HEIGHT constraint if AUTO_DOWNSCALE is enabled
        if self.config.AUTO_DOWNSCALE and target_height > self.config.MAX_HEIGHT:
            scale = self.config.MAX_HEIGHT / target_height
            target_width = int(target_width * scale)
            target_height = self.config.MAX_HEIGHT
            # Re-apply divisibility
            target_width = (target_width // 32) * 32
            target_height = (target_height // 32) * 32
            target_width = max(target_width, 128)
            target_height = max(target_height, 128)
            logger.info(f"📏 Applying MAX_HEIGHT constraint: downscaled to {target_width}x{target_height}")
        
        return target_width, target_height, final_chunk

    def calculate_target_dimensions(self, width, height, gpu_vram_gb=None):
        """
        Backward compatibility wrapper.
        If gpu_vram_gb is None, uses default VRAM (8GB) for safety.
        """
        if gpu_vram_gb is None:
            # Assume minimal VRAM for safety
            gpu_vram_gb = 8.0
        target_width, target_height, _ = self.calculate_optimal_params(width, height, gpu_vram_gb)
        return target_width, target_height
    
    def ensure_divisible_by_32(self, width, height):
        """
        Ensure dimensions are divisible by 32 (RAFT requirement).
        Used for backward compatibility with tests.
        """
        width = (width // 32) * 32
        height = (height // 32) * 32
        width = max(width, 32)
        height = max(height, 32)
        return width, height
    
    def should_downscale(self, height):
        """
        Determine if downscaling is needed based on config.
        Used for backward compatibility with tests.
        """
        if not self.config.AUTO_DOWNSCALE:
            return False
        return height > self.config.MAX_HEIGHT
