"""
Configuration constants for watermark removal fine-tuning.

This module contains all tunable parameters for watermark detection and removal.
Adjust these values to control static detection sensitivity and mask quality.

Last updated: 2026-01-09
"""

# =============================================================================
# STATIC WATERMARK DETECTION
# =============================================================================

# Persistence threshold: minimum ratio of frames a pixel must appear in (0.0 to 1.0)
# Higher = stricter (only very persistent pixels are marked as watermark)
# Lower = more sensitive (catches semi-transparent or fading watermarks)
# Default: 0.80 (pixel must appear in 80% of sampled frames)
# Recommended range: 0.60 (sensitive) to 0.95 (strict)
PERSISTENCE_THRESHOLD = 0.80

# Number of frames to sample for static detection (from total frames)
# Higher = more accurate but slower
# Lower = faster but may miss intermittent watermarks
# Default: 30 (sample up to 30 frames evenly distributed)
# Recommended range: 10 (fast) to 50 (accurate)
SAMPLE_FRAME_COUNT = 30

# Minimum persistent region area (pixels) to keep as watermark
# Filters out small noise regions (dust, compression artifacts)
# Higher = removes more small regions (conservative)
# Lower = keeps small watermarks (sensitive)
# Default: 100 pixels
# Recommended range: 50 (sensitive) to 500 (conservative)
MIN_REGION_AREA = 100

# Maximum persistent region area (% of frame)
# Filters out large false detections (static backgrounds)
# Higher = allows larger watermarks
# Lower = more conservative (rejects large regions)
# Default: 0.15 (15% of frame)
# Recommended range: 0.05 (strict) to 0.30 (permissive)
MAX_REGION_AREA_RATIO = 0.15


# =============================================================================
# COLOR-AWARE DETECTION
# =============================================================================

# Enable color-aware detection (detects colored watermarks)
# When True: analyzes RGB channels separately (catches colored logos)
# When False: grayscale only (faster, but misses colored watermarks)
# Default: True (recommended for most cases)
USE_COLOR_DETECTION = True

# Color difference threshold for static detection (0-255)
# Lower = more sensitive to color changes (may miss semi-transparent watermarks)
# Higher = less sensitive (better for fading/animated watermarks)
# Default: 30 (moderate sensitivity)
# Recommended range: 10 (strict) to 50 (permissive)
COLOR_DIFF_THRESHOLD = 30


# =============================================================================
# EDGE DETECTION (for watermark boundaries)
# =============================================================================

# Canny edge detection: low threshold
# Lower = more edges detected (sensitive)
# Higher = fewer edges detected (conservative)
# Default: 50
# Recommended range: 30 to 100
EDGE_DETECTION_LOW_THRESHOLD = 50

# Canny edge detection: high threshold
# Should be 2-3x the low threshold
# Default: 150
# Recommended range: 100 to 200
EDGE_DETECTION_HIGH_THRESHOLD = 150

# Edge dilation kernel size (to close gaps in watermark edges)
# Larger = more aggressive edge closure
# Smaller = preserves fine details
# Default: 3
# Recommended range: 1 (minimal) to 5 (aggressive)
EDGE_DILATION_KERNEL = 3


# =============================================================================
# MASK EXPANSION
# =============================================================================

# Mask expansion radius (pixels) around detected watermark
# Ensures complete watermark removal (catches blur, glow, shadows)
# Higher = more aggressive (may remove surrounding content)
# Lower = more precise (may leave watermark artifacts)
# Default: 10 pixels
# Recommended range: 5 (precise) to 20 (aggressive)
MASK_EXPANSION_RADIUS = 10

# Morphological closing kernel size (fills gaps in mask)
# Larger = fills larger gaps (good for broken watermarks)
# Smaller = preserves mask details
# Default: 5
# Recommended range: 3 (conservative) to 9 (aggressive)
MORPHOLOGICAL_CLOSING_KERNEL = 5

# Gaussian blur sigma for mask smoothing
# Higher = smoother mask edges (better blending)
# Lower = sharper edges (more precise)
# Default: 2.0
# Recommended range: 1.0 (sharp) to 5.0 (smooth)
MASK_BLUR_SIGMA = 2.0


# =============================================================================
# ASPECT RATIO VALIDATION
# =============================================================================

# Maximum allowed aspect ratio difference (for validation)
# Warns if ProPainter changes aspect ratio by more than this
# Default: 0.05 (5%)
# Recommended range: 0.01 (strict) to 0.10 (permissive)
MAX_ASPECT_RATIO_DIFF = 0.05


# =============================================================================
# OCR-BASED FALLBACK (per-frame detection)
# =============================================================================

# OCR confidence threshold for fallback mode (when static detection is disabled)
# Lower = more aggressive text detection
# Higher = only high-confidence text
# Default: 0.01 (very aggressive, catches watermark text)
# Recommended range: 0.01 to 0.10
OCR_FALLBACK_CONFIDENCE = 0.01

# Mask dilation kernel for OCR-detected watermarks
# Larger = more expansion around detected text
# Default: 15 pixels
# Recommended range: 5 to 30
OCR_FALLBACK_EXPANSION = 15


# =============================================================================
# PERFORMANCE OPTIMIZATION
# =============================================================================

# Downscale factor for static detection (speeds up processing)
# 1.0 = full resolution (accurate but slow)
# 0.5 = half resolution (2x faster, still good)
# 0.25 = quarter resolution (4x faster, less accurate)
# Default: 0.5
# Recommended range: 0.25 (fast) to 1.0 (accurate)
DETECTION_SCALE_FACTOR = 0.5

# Enable GPU acceleration for static detection
# When True: uses GPU for image processing (faster)
# When False: CPU only (slower but more compatible)
# Default: True
USE_GPU_DETECTION = True


# =============================================================================
# ROI PRESETS (for common watermark locations)
# =============================================================================

# Default ROI for watermark removal
# Common locations: 'top-right', 'top-left', 'bottom-right', 'bottom-left', 'center'
DEFAULT_WATERMARK_ROI = 'top-right'

# ROI size multiplier (for preset ROIs)
# Default presets use 20% of frame width/height
# This multiplier can increase/decrease that
# Default: 1.0 (20% x 20%)
# Recommended range: 0.5 (10% x 10%) to 2.0 (40% x 40%)
ROI_SIZE_MULTIPLIER = 1.0


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_scaled_dimensions(width: int, height: int) -> tuple[int, int]:
    """
    Get scaled dimensions for static detection based on DETECTION_SCALE_FACTOR.

    Args:
        width: Original frame width
        height: Original frame height

    Returns:
        Tuple of (scaled_width, scaled_height)
    """
    scaled_w = int(width * DETECTION_SCALE_FACTOR)
    scaled_h = int(height * DETECTION_SCALE_FACTOR)

    # Ensure dimensions are at least 32 (minimum for most operations)
    scaled_w = max(32, scaled_w)
    scaled_h = max(32, scaled_h)

    return scaled_w, scaled_h


def validate_config():
    """Validate configuration values and warn about extreme settings."""
    import logging
    logger = logging.getLogger(__name__)

    warnings = []

    # Check persistence threshold
    if PERSISTENCE_THRESHOLD < 0.5:
        warnings.append(f"⚠️  PERSISTENCE_THRESHOLD={PERSISTENCE_THRESHOLD} is low (may detect non-persistent objects)")
    elif PERSISTENCE_THRESHOLD > 0.95:
        warnings.append(f"⚠️  PERSISTENCE_THRESHOLD={PERSISTENCE_THRESHOLD} is very high (may miss semi-transparent watermarks)")

    # Check mask expansion
    if MASK_EXPANSION_RADIUS > 30:
        warnings.append(f"⚠️  MASK_EXPANSION_RADIUS={MASK_EXPANSION_RADIUS}px is large (may remove non-watermark content)")

    # Check scale factor
    if DETECTION_SCALE_FACTOR < 0.25:
        warnings.append(f"⚠️  DETECTION_SCALE_FACTOR={DETECTION_SCALE_FACTOR} is very low (may miss small watermarks)")

    # Check sample count
    if SAMPLE_FRAME_COUNT < 10:
        warnings.append(f"⚠️  SAMPLE_FRAME_COUNT={SAMPLE_FRAME_COUNT} is low (may miss intermittent watermarks)")

    # Log warnings
    if warnings:
        logger.warning("=== Watermark Removal Config Validation ===")
        for warning in warnings:
            logger.warning(warning)
        logger.warning("===========================================")


# =============================================================================
# PRESET PROFILES
# =============================================================================

class WatermarkProfile:
    """Predefined profiles for common watermark types."""

    @staticmethod
    def opaque_logo():
        """For solid, opaque watermarks (e.g., channel logos)."""
        return {
            'PERSISTENCE_THRESHOLD': 0.90,
            'COLOR_DIFF_THRESHOLD': 20,
            'MASK_EXPANSION_RADIUS': 8,
            'MIN_REGION_AREA': 200,
        }

    @staticmethod
    def transparent_overlay():
        """For semi-transparent watermarks (e.g., faded logos)."""
        return {
            'PERSISTENCE_THRESHOLD': 0.70,
            'COLOR_DIFF_THRESHOLD': 40,
            'MASK_EXPANSION_RADIUS': 12,
            'MIN_REGION_AREA': 100,
        }

    @staticmethod
    def small_text():
        """For small text watermarks (e.g., copyright notices)."""
        return {
            'PERSISTENCE_THRESHOLD': 0.85,
            'MASK_EXPANSION_RADIUS': 15,
            'MIN_REGION_AREA': 50,
            'OCR_FALLBACK_CONFIDENCE': 0.05,
        }

    @staticmethod
    def large_banner():
        """For large banner watermarks (e.g., TV station bugs)."""
        return {
            'PERSISTENCE_THRESHOLD': 0.80,
            'MAX_REGION_AREA_RATIO': 0.25,
            'MASK_EXPANSION_RADIUS': 10,
            'MIN_REGION_AREA': 500,
        }

    @staticmethod
    def animated_watermark():
        """For animated/fading watermarks (challenging case)."""
        return {
            'PERSISTENCE_THRESHOLD': 0.60,
            'SAMPLE_FRAME_COUNT': 50,
            'COLOR_DIFF_THRESHOLD': 50,
            'MASK_EXPANSION_RADIUS': 12,
        }


def apply_profile(profile_name: str):
    """
    Apply a preset profile to global config.

    Args:
        profile_name: 'opaque_logo', 'transparent_overlay', 'small_text',
                      'large_banner', or 'animated_watermark'
    """
    import sys

    profiles = {
        'opaque_logo': WatermarkProfile.opaque_logo(),
        'transparent_overlay': WatermarkProfile.transparent_overlay(),
        'small_text': WatermarkProfile.small_text(),
        'large_banner': WatermarkProfile.large_banner(),
        'animated_watermark': WatermarkProfile.animated_watermark(),
    }

    if profile_name not in profiles:
        raise ValueError(f"Unknown profile: {profile_name}. Available: {list(profiles.keys())}")

    profile = profiles[profile_name]
    current_module = sys.modules[__name__]

    for key, value in profile.items():
        setattr(current_module, key, value)

    return profile


# =============================================================================
# DEBUGGING HELPERS
# =============================================================================

def print_current_config():
    """Print all current configuration values (useful for debugging)."""
    import sys
    current_module = sys.modules[__name__]

    print("=== Watermark Removal Configuration ===")
    print("\n[Static Detection]")
    print(f"  PERSISTENCE_THRESHOLD = {PERSISTENCE_THRESHOLD}")
    print(f"  SAMPLE_FRAME_COUNT = {SAMPLE_FRAME_COUNT}")
    print(f"  MIN_REGION_AREA = {MIN_REGION_AREA}")
    print(f"  MAX_REGION_AREA_RATIO = {MAX_REGION_AREA_RATIO}")

    print("\n[Color Detection]")
    print(f"  USE_COLOR_DETECTION = {USE_COLOR_DETECTION}")
    print(f"  COLOR_DIFF_THRESHOLD = {COLOR_DIFF_THRESHOLD}")

    print("\n[Mask Processing]")
    print(f"  MASK_EXPANSION_RADIUS = {MASK_EXPANSION_RADIUS}")
    print(f"  MORPHOLOGICAL_CLOSING_KERNEL = {MORPHOLOGICAL_CLOSING_KERNEL}")
    print(f"  MASK_BLUR_SIGMA = {MASK_BLUR_SIGMA}")

    print("\n[Performance]")
    print(f"  DETECTION_SCALE_FACTOR = {DETECTION_SCALE_FACTOR}")
    print(f"  USE_GPU_DETECTION = {USE_GPU_DETECTION}")

    print("=" * 40)

