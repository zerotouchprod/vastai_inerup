"""
Masking package - provides the ultimate hybrid text detection service.
"""

from .service import HybridMaskService

# Primary export: MaskService (the main class)
MaskService = HybridMaskService

# Alias for backward compatibility with existing imports
MaskGeneratorService = HybridMaskService

__all__ = [
    'MaskService',
    'MaskGeneratorService',
    'HybridMaskService',
]
