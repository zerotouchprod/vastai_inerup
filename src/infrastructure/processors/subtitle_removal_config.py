"""
Configuration constants for subtitle removal fine-tuning.

This module contains all tunable parameters for subtitle detection and removal.
Adjust these values to control aggressiveness, sensitivity, and quality.

Last updated: 2026-01-09
"""

# =============================================================================
# OCR DETECTION SENSITIVITY
# =============================================================================

# Minimum confidence threshold for OCR text detection (0.0 to 1.0)
# Lower = more aggressive (catches more text, including false positives)
# Higher = more conservative (misses some subtle text)
# Default: 0.05 (very aggressive, catches short words like "на", "и", "в")
# Recommended range: 0.01 (ultra-aggressive) to 0.15 (conservative)
OCR_CONFIDENCE_THRESHOLD = 0.05

# Run OCR on both enhanced and original images (True = better detection, 2x slower)
# When True: runs CLAHE enhancement + original, merges results
# When False: runs only on enhanced image
# Default: True (catches text that is visible in only one variant)
OCR_DUAL_PASS_ENABLED = True

# IoU threshold for merging duplicate detections from dual-pass OCR
# Higher = stricter deduplication (may keep near-duplicates)
# Lower = aggressive deduplication (may merge distinct boxes)
# Default: 0.3 (30% overlap = considered duplicate)
# Recommended range: 0.2 to 0.5
OCR_DUPLICATE_IOU_THRESHOLD = 0.3


# =============================================================================
# BOUNDING BOX EXPANSION
# =============================================================================

# Horizontal expansion around detected text (pixels)
# Catches text glow, shadows, outline effects
# Default: 15px
# Recommended range: 5px (minimal) to 30px (aggressive)
BBOX_EXPAND_HORIZONTAL = 15

# Vertical expansion around detected text (pixels)
# Catches descenders, ascenders, vertical glow
# Default: 20px
# Recommended range: 10px (minimal) to 40px (aggressive)
BBOX_EXPAND_VERTICAL = 20


# =============================================================================
# MASK DILATION (VRAM-ADAPTIVE)
# =============================================================================

# These values are overridden by VRAM detection but can be forced by setting
# environment variable FORCE_KERNEL_SIZE (e.g., FORCE_KERNEL_SIZE=40)

# Kernel size for <8GB VRAM (e.g., RTX 3060, RTX 4060)
# Smaller = less aggressive, faster, lower memory usage
# Default: 30x30
KERNEL_SIZE_LOW_VRAM = 30

# Kernel size for 8-16GB VRAM (e.g., RTX 3080, RTX 4070)
# Balanced between coverage and performance
# Default: 40x40
KERNEL_SIZE_MID_VRAM = 40

# Kernel size for >16GB VRAM (e.g., RTX 4090, RTX 5090)
# Larger = more aggressive, captures full glow/shadow extent
# Default: 45x45
KERNEL_SIZE_HIGH_VRAM = 45

# Number of dilation iterations (applied BEFORE morphological closing)
# Higher = more aggressive expansion of mask
# Default: 2
# Recommended range: 1 (conservative) to 3 (aggressive)
DILATION_ITERATIONS_INITIAL = 2

# Number of morphological closing iterations (fills gaps between letters)
# Higher = fills larger gaps (good for spaced text, bad for separate objects)
# Default: 1
# Recommended range: 1 to 2
MORPHOLOGICAL_CLOSING_ITERATIONS = 1

# Number of final dilation iterations (applied AFTER closing)
# Higher = further expansion of final mask
# Default: 1
# Recommended range: 0 (no final dilation) to 2 (aggressive)
DILATION_ITERATIONS_FINAL = 1


# =============================================================================
# CLAHE ENHANCEMENT (for OCR preprocessing)
# =============================================================================

# CLAHE clip limit (controls contrast enhancement strength)
# Higher = stronger enhancement (may introduce noise)
# Lower = gentler enhancement (may miss low-contrast text)
# Default: 4.0
# Recommended range: 2.0 (gentle) to 6.0 (aggressive)
CLAHE_CLIP_LIMIT = 4.0

# CLAHE tile grid size (smaller = more localized enhancement)
# Default: (8, 8)
# Alternative: (4, 4) for finer detail, (16, 16) for smoother
CLAHE_TILE_GRID_SIZE = (8, 8)


# =============================================================================
# MEMORY OPTIMIZATION
# =============================================================================

# GPU memory cleanup interval (frames)
# Run torch.cuda.empty_cache() every N frames
# Lower = more frequent cleanup (slower, but safer for low-VRAM GPUs)
# Higher = less frequent cleanup (faster, but may OOM on 6GB GPUs)
# Default: 50
# Recommended range: 20 (RTX 3060) to 100 (RTX 4090)
GPU_CLEANUP_INTERVAL = 50


# =============================================================================
# PROGRESS LOGGING
# =============================================================================

# Log progress every N% of frames
# Lower = more frequent logs (verbose)
# Higher = less frequent logs (cleaner output)
# Default: 10 (log at 10%, 20%, 30%, etc.)
PROGRESS_LOG_PERCENTAGE = 10


# =============================================================================
# DEBUG MODE SETTINGS
# =============================================================================

# Number of example filtered boxes to log per frame (DEBUG level only)
# Lower = cleaner logs
# Higher = more diagnostic info
# Default: 3
DEBUG_MAX_FILTERED_EXAMPLES = 3


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_kernel_size_for_vram(vram_gb: float) -> int:
    """
    Get optimal kernel size based on available VRAM.
    Can be overridden with FORCE_KERNEL_SIZE environment variable.
    """
    import os

    # Check for manual override
    force_size = os.environ.get('FORCE_KERNEL_SIZE')
    if force_size:
        try:
            size = int(force_size)
            if size > 0:
                return size
        except ValueError:
            pass

    # Auto-detect based on VRAM
    if vram_gb < 8:
        return KERNEL_SIZE_LOW_VRAM
    elif vram_gb < 16:
        return KERNEL_SIZE_MID_VRAM
    else:
        return KERNEL_SIZE_HIGH_VRAM


def validate_config():
    """Validate configuration values and warn about extreme settings."""
    import logging
    logger = logging.getLogger(__name__)

    warnings = []

    # Check OCR threshold
    if OCR_CONFIDENCE_THRESHOLD < 0.01:
        warnings.append(f"⚠️  OCR_CONFIDENCE_THRESHOLD={OCR_CONFIDENCE_THRESHOLD} is very low (may cause false positives)")
    elif OCR_CONFIDENCE_THRESHOLD > 0.2:
        warnings.append(f"⚠️  OCR_CONFIDENCE_THRESHOLD={OCR_CONFIDENCE_THRESHOLD} is high (may miss subtle text)")

    # Check bbox expansion
    if BBOX_EXPAND_HORIZONTAL > 50 or BBOX_EXPAND_VERTICAL > 50:
        warnings.append(f"⚠️  Bounding box expansion is very large (may remove non-text areas)")

    # Check dilation iterations
    total_dilation = DILATION_ITERATIONS_INITIAL + DILATION_ITERATIONS_FINAL
    if total_dilation > 5:
        warnings.append(f"⚠️  Total dilation iterations={total_dilation} is very high (may blur too much)")

    # Log warnings
    if warnings:
        logger.warning("=== Subtitle Removal Config Validation ===")
        for warning in warnings:
            logger.warning(warning)
        logger.warning("==========================================")


# =============================================================================
# PRESET PROFILES
# =============================================================================

class DetectionProfile:
    """Predefined profiles for common use cases."""

    @staticmethod
    def conservative():
        """Conservative profile: minimal false positives, may miss some text."""
        return {
            'OCR_CONFIDENCE_THRESHOLD': 0.15,
            'BBOX_EXPAND_HORIZONTAL': 10,
            'BBOX_EXPAND_VERTICAL': 15,
            'DILATION_ITERATIONS_INITIAL': 1,
            'DILATION_ITERATIONS_FINAL': 1,
        }

    @staticmethod
    def balanced():
        """Balanced profile: default settings (recommended)."""
        return {
            'OCR_CONFIDENCE_THRESHOLD': 0.05,
            'BBOX_EXPAND_HORIZONTAL': 15,
            'BBOX_EXPAND_VERTICAL': 20,
            'DILATION_ITERATIONS_INITIAL': 2,
            'DILATION_ITERATIONS_FINAL': 1,
        }

    @staticmethod
    def aggressive():
        """Aggressive profile: catch all text, may have false positives."""
        return {
            'OCR_CONFIDENCE_THRESHOLD': 0.01,
            'BBOX_EXPAND_HORIZONTAL': 25,
            'BBOX_EXPAND_VERTICAL': 30,
            'DILATION_ITERATIONS_INITIAL': 3,
            'DILATION_ITERATIONS_FINAL': 2,
        }

    @staticmethod
    def minimal():
        """Minimal profile: only obvious text, minimal mask expansion."""
        return {
            'OCR_CONFIDENCE_THRESHOLD': 0.20,
            'BBOX_EXPAND_HORIZONTAL': 5,
            'BBOX_EXPAND_VERTICAL': 10,
            'DILATION_ITERATIONS_INITIAL': 1,
            'DILATION_ITERATIONS_FINAL': 0,
        }


def apply_profile(profile_name: str):
    """
    Apply a preset profile to global config.

    Args:
        profile_name: 'conservative', 'balanced', 'aggressive', or 'minimal'
    """
    import sys

    profiles = {
        'conservative': DetectionProfile.conservative(),
        'balanced': DetectionProfile.balanced(),
        'aggressive': DetectionProfile.aggressive(),
        'minimal': DetectionProfile.minimal(),
    }

    if profile_name not in profiles:
        raise ValueError(f"Unknown profile: {profile_name}. Available: {list(profiles.keys())}")

    profile = profiles[profile_name]
    current_module = sys.modules[__name__]

    for key, value in profile.items():
        setattr(current_module, key, value)

    return profile

