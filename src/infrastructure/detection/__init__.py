"""
Detection module для v2.1 - Animated Text Detection.

Включает:
- OpticalFlowTracker - отслеживание движения через optical flow
- TemporalMaskPropagator - propagation масок через keyframes
- ColorChangeDetector - детекция караоке-субтитров
- AnimatedTextDetector - главный координатор

Version: 2.1.0
"""

from .optical_flow_tracker import OpticalFlowTracker, FlowParameters
from .temporal_mask_propagator import TemporalMaskPropagator
from .color_change_detector import ColorChangeDetector
from .animated_text_detector import AnimatedTextDetector

__all__ = [
    'OpticalFlowTracker',
    'FlowParameters',
    'TemporalMaskPropagator',
    'ColorChangeDetector',
    'AnimatedTextDetector',
]

__version__ = '2.1.0'

