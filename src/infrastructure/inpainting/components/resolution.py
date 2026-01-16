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
        
        🚨 FIX: Если система видит > 30GB (мульти-гпу), делим пополам для безопасности,
        так как процесс использует только одну карту.
        
        Returns:
            (target_width, target_height, optimal_chunk_size)
        """
        # 🚨 FIX: Если система видит > 30GB (мульти-гпу), делим пополам для безопасности,
        # так как процесс использует только одну карту.
        if vram_gb > 30.0:
            logger.warning(f"Detected dual-GPU VRAM sum ({vram_gb:.1f}GB). Using single-GPU estimate.")
            vram_gb = vram_gb / 2  # Предполагаем 2 одинаковые карты
            
        # 1. Apply Hard Config Limits FIRST
        # Если видео выше MAX_HEIGHT, сразу применяем лимит
        limit_height = self.config.MAX_HEIGHT
        
        if original_height > limit_height:
            scale = limit_height / original_height
            calc_width = int(original_width * scale)
            calc_height = limit_height
            logger.info(f"📉 Applying Config Limit: {original_width}x{original_height} -> {calc_width}x{calc_height}")
        else:
            calc_width = original_width
            calc_height = original_height

        # 2. Base constraints
        # RAFT requires decent VRAM. ProPainter overhead is ~3GB static + dynamic.
        usable_vram = max(0, vram_gb - 3.0)  # Reserve 3GB for system/torch overhead
        
        # Pixels in millions (using the LIMITED resolution)
        mp = (calc_width * calc_height) / 1_000_000
        if mp <= 0: mp = 0.1
        
        # Calculate max frames for the TARGET resolution
        # FP16 factor approx 0.55 GB per MP per frame (AMP-friendly)
        max_safe_frames = int(usable_vram / (mp * 0.55))
        
        MIN_FRAMES = 3  # Minimum needed for temporal consistency
        
        logger.info(f"🧮 Single-GPU VRAM: {usable_vram:.1f}GB usable. Target Res: {calc_width}x{calc_height}")
        
        # --- DECISION LOGIC ---
        if max_safe_frames >= MIN_FRAMES:
            final_chunk = min(max_safe_frames, self.config.MAX_FRAMES_PER_CHUNK)
            target_width = calc_width
            target_height = calc_height
            logger.info(f"✅ Resolution fits! Chunk size: {final_chunk}")
        else:
            # Emergency Downscale (если даже ограниченное разрешение не влезает)
            logger.warning(f"⚠️ {calc_height}p is still too heavy. Emergency downscale.")
            target_mp = usable_vram / (MIN_FRAMES * 0.55)
            scale = math.sqrt(target_mp / mp)
            target_width = int(calc_width * scale)
            target_height = int(calc_height * scale)
            final_chunk = MIN_FRAMES

        # --- FINAL ADJUSTMENTS ---
        # 1. Ensure Divisible by 32 (Requirement for RAFT/ProPainter)
        target_width = (target_width // 32) * 32
        target_height = (target_height // 32) * 32
        
        # Ensure minimal dimensions
        target_width = max(target_width, 128)
        target_height = max(target_height, 128)
        
        # 2. Apply MAX_HEIGHT constraint if AUTO_DOWNSCALE is enabled
        # (Уже применено в начале, но проверяем на всякий случай)
        if (self.config.AUTO_DOWNSCALE and target_height > self.config.MAX_HEIGHT):
            scale = self.config.MAX_HEIGHT / target_height
            target_width = int(target_width * scale)
            target_height = self.config.MAX_HEIGHT
            # Re-apply divisibility
            target_width = (target_width // 32) * 32
            target_height = (target_height // 32) * 32
            target_width = max(target_width, 128)
            target_height = max(target_height, 128)
            logger.info(f"📏 Final MAX_HEIGHT constraint: downscaled to {target_width}x{target_height}")
        
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
