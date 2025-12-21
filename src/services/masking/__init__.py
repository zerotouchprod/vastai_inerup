"""
Masking package - provides the ultimate hybrid text detection service.
"""

from ..mask_service import MaskGeneratorService

# Primary export: MaskService (the main class)
MaskService = MaskGeneratorService

# Alias for backward compatibility with existing imports
HybridMaskService = MaskGeneratorService

__all__ = [
    'MaskService',
    'MaskGeneratorService',
    'HybridMaskService',
]
