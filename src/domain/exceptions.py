"""Domain exceptions for the video processing pipeline."""


class DomainException(Exception):
    """Base exception for all domain errors."""
    pass


class VideoProcessingError(DomainException):
    """Raised when video processing fails."""
    pass


class DownloadError(DomainException):
    """Raised when file download fails."""
    pass


class UploadError(DomainException):
    """Raised when file upload fails."""
    pass


class ConfigurationError(DomainException):
    """Raised when configuration is invalid."""
    pass


class ExtractionError(DomainException):
    """Raised when frame extraction fails."""
    pass


class AssemblyError(DomainException):
    """Raised when video assembly fails."""
    pass


class ProcessorNotAvailableError(DomainException):
    """Raised when requested processor is not available."""
    pass


class GPURequiredError(DomainException):
    """Raised when GPU is required but not available."""
    pass


class GenerationError(DomainException):
    """Raised when video generation fails."""
    pass


class ModelNotLoadedError(GenerationError):
    """Raised when attempting to use uninitialized model."""
    pass


class NSFWContentError(GenerationError):
    """Raised when NSFW content is detected."""
    pass


