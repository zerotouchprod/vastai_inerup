"""
Custom exceptions for subtitle removal application.
"""


class SubtitleRemovalError(Exception):
    """Base exception for subtitle removal errors."""
    pass


class OCRInitializationError(SubtitleRemovalError):
    """Failed to initialize OCR engine."""
    pass


class ModelLoadingError(SubtitleRemovalError):
    """Failed to load AI model."""
    pass


class DeviceInitializationError(SubtitleRemovalError):
    """Failed to initialize device (GPU/CPU)."""
    pass


class VideoIOError(SubtitleRemovalError):
    """Failed to read/write video frames."""
    pass


class ConfigurationError(SubtitleRemovalError):
    """Configuration error."""
    pass


class ProcessingError(SubtitleRemovalError):
    """Error during processing."""
    pass


class ProcessorNotAvailableError(SubtitleRemovalError):
    """Processor/engine not available."""
    pass
