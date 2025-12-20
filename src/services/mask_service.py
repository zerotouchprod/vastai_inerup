"""
Legacy wrapper for backward compatibility.
Imports the new modular MaskService from the masking package.
"""

import logging
import warnings

logger = logging.getLogger(__name__)

# Show deprecation warning
warnings.warn(
    "Importing MaskService from src.services.mask_service is deprecated. "
    "Use from src.services.masking import MaskService instead.",
    DeprecationWarning,
    stacklevel=2
)

# Import the new implementation
try:
    from src.services.masking import MaskService, MaskGeneratorService
except ImportError as e:
    logger.error(f"Failed to import new MaskService: {e}")
    raise

# Re-export the same classes
__all__ = ['MaskService', 'MaskGeneratorService']
