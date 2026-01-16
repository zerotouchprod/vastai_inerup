"""
Application Startup Hook for CUDA Extension Validation
=======================================================

Senior Python approach to runtime dependency validation.

This module provides startup hooks that should be called by the application
BEFORE any processing starts, regardless of how the container was started
(entrypoint, SSH, direct Python, etc.)

Usage in main application entry point:
    
    from src.infrastructure.startup import validate_cuda_dependencies
    
    def main():
        # Validate dependencies at startup
        validate_cuda_dependencies()
        
        # Continue with application logic
        ...
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_cuda_dependencies(auto_rebuild: bool = None) -> bool:
    """
    Validate CUDA-dependent extensions at application startup.
    
    This should be called at the very beginning of your application,
    before importing any CUDA-dependent code.
    
    Args:
        auto_rebuild: Whether to attempt automatic rebuild if broken.
                     If None, reads from AUTO_REBUILD_CUDA_EXTENSIONS env var.
                     Default: False (fail fast, don't attempt rebuild)
    
    Returns:
        bool: True if all dependencies are working
        
    Raises:
        RuntimeError: If dependencies are broken and auto_rebuild=False
        
    Design patterns:
    - Fail fast: Validate at startup, not during processing
    - Clear errors: Provide actionable error messages
    - Configurability: Allow auto-rebuild via env var or parameter
    - Single responsibility: Only validates dependencies
    
    Example usage:
        # In your main.py or __main__ module
        from src.infrastructure.startup import validate_cuda_dependencies
        
        if __name__ == '__main__':
            # Fail fast if CUDA extensions are broken
            validate_cuda_dependencies()
            
            # Rest of your application
            main()
    """
    from datetime import datetime

    if auto_rebuild is None:
        # Default to TRUE for self-healing behavior on Vast.ai
        # Set AUTO_REBUILD_CUDA_EXTENSIONS=false to disable
        auto_rebuild = os.getenv("AUTO_REBUILD_CUDA_EXTENSIONS", "true").lower() == "true"

    # Check if pure PyTorch correlation should be used (no C++ extension)
    use_pure_pytorch = os.getenv("USE_PURE_PYTORCH_CORRELATION", "false").lower() == "true"

    logger.info("=" * 80)
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] STARTUP: Validating CUDA dependencies...")
    logger.info("=" * 80)
    
    # Option 1: Use pure PyTorch correlation (no C++ extension needed)
    if use_pure_pytorch:
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Using pure PyTorch correlation (no C++ extension)")
        try:
            from src.infrastructure.inpainting.pure_pytorch_correlation import install_pure_pytorch_correlation
            install_pure_pytorch_correlation()
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Pure PyTorch correlation installed")
            logger.info("=" * 80)
            return True
        except Exception as e:
            logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to install pure PyTorch correlation: {e}")
            logger.error("Falling back to spatial-correlation-sampler check...")

    # Option 2: Check/rebuild spatial-correlation-sampler (legacy C++ extension)
    try:
        from src.infrastructure.inpainting.raft_wrapper import (
            check_spatial_correlation_sampler,
            rebuild_spatial_correlation_sampler,
            SpatialCorrelationSamplerError,
            CUDAExtensionRebuiltError  # New exception type
        )
        
        # Check spatial-correlation-sampler
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Checking spatial-correlation-sampler...")
        is_working, error = check_spatial_correlation_sampler()
        
        if is_working:
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ spatial-correlation-sampler: OK")
            logger.info("=" * 80)
            return True
        
        # Not working - log error
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ spatial-correlation-sampler: BROKEN")
        logger.error(f"Error: {error}")
        logger.error("")
        
        # Attempt rebuild if enabled
        if auto_rebuild:
            logger.warning(f"[{datetime.now().strftime('%H:%M:%S')}] Attempting auto-rebuild (default behavior on Vast.ai)...")
            logger.warning("This will take ~60-180 seconds...")
            logger.warning("Set AUTO_REBUILD_CUDA_EXTENSIONS=false to disable")
            logger.warning("")
            
            # rebuild_spatial_correlation_sampler() will raise CUDAExtensionRebuiltError
            # if successful - we don't catch it here, let it propagate to main()
            rebuild_spatial_correlation_sampler()

            # Should never reach here - rebuild either raises or returns False
            logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ spatial-correlation-sampler: REBUILT SUCCESSFULLY")
            logger.info("=" * 80)
            return True
        else:
            logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-rebuild is DISABLED (AUTO_REBUILD_CUDA_EXTENSIONS=false)")

        # Failed - provide clear instructions
        logger.error("")
        logger.error("=" * 80)
        logger.error("CRITICAL: spatial-correlation-sampler is BROKEN")
        logger.error("=" * 80)
        logger.error("")
        logger.error("What this means:")
        logger.error("  - Docker image was built with different CUDA version than runtime")
        logger.error("  - ProPainter RAFT will NOT work")
        logger.error("  - Video processing will FAIL")
        logger.error("")
        logger.error("How to fix (in order of preference):")
        logger.error("")
        logger.error("  1. REBUILD DOCKER IMAGE with correct CUDA version:")
        logger.error("     docker build -t your-image:latest .")
        logger.error("")
        logger.error("  2. Wait for auto-rebuild to complete (default, ~60-180 sec)")
        logger.error("     If you see this message, rebuild may have failed")
        logger.error("")
        logger.error("  3. Manual rebuild (for debugging):")
        logger.error("     pip install --force-reinstall --no-binary spatial-correlation-sampler spatial-correlation-sampler")
        logger.error("")
        logger.error("  4. Use different GPU instance with matching CUDA version")
        logger.error("")
        logger.error("=" * 80)
        
        raise RuntimeError(
            "spatial-correlation-sampler is broken. "
            "See logs above for detailed fix instructions. "
            "Docker image must be rebuilt with correct CUDA version."
        )
        
    except CUDAExtensionRebuiltError:
        # Rebuild succeeded! Re-raise so main() can return exit code 42
        raise

    except ImportError as e:
        logger.error(f"❌ Failed to import validation modules: {e}")
        logger.error("This indicates a code deployment issue")
        logger.error("=" * 80)
        raise RuntimeError(f"Code deployment error: {e}")
    
    except Exception as e:
        logger.error(f"❌ Unexpected error during validation: {e}")
        logger.error("=" * 80)
        raise


def validate_propainter() -> bool:
    """
    Validate that ProPainter is installed and working.
    
    Returns:
        bool: True if ProPainter is available
        
    Raises:
        RuntimeError: If ProPainter is not installed or broken
    """
    logger.info("Validating ProPainter installation...")
    
    try:
        from src.infrastructure.inpainting.raft_wrapper import validate_raft_availability
        
        validate_raft_availability()
        logger.info("✅ ProPainter RAFT: OK")
        return True
        
    except Exception as e:
        logger.error(f"❌ ProPainter validation failed: {e}")
        raise RuntimeError(f"ProPainter is not working: {e}")


def startup_checks(
    validate_cuda: bool = True,
    validate_propainter_raft: bool = True,
    auto_rebuild: bool = None
) -> None:
    """
    Run all startup validation checks.
    
    Call this at the very beginning of your application.
    
    Args:
        validate_cuda: Whether to validate CUDA dependencies
        validate_propainter_raft: Whether to validate ProPainter RAFT
        auto_rebuild: Whether to attempt automatic rebuild if broken
        
    Raises:
        RuntimeError: If any validation fails
        
    Example:
        # In your main entry point
        from src.infrastructure.startup import startup_checks
        
        if __name__ == '__main__':
            startup_checks()  # Fail fast if dependencies broken
            main()  # Your application logic
    """
    logger.info("")
    logger.info("=" * 80)
    logger.info("APPLICATION STARTUP VALIDATION")
    logger.info("=" * 80)
    logger.info("")
    
    if validate_cuda:
        validate_cuda_dependencies(auto_rebuild=auto_rebuild)
        logger.info("")
    
    if validate_propainter_raft:
        validate_propainter()
        logger.info("")
    
    logger.info("=" * 80)
    logger.info("✅ ALL STARTUP CHECKS PASSED")
    logger.info("=" * 80)
    logger.info("")


# Convenient exports
__all__ = [
    'validate_cuda_dependencies',
    'validate_propainter',
    'startup_checks',
]

