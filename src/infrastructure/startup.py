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


def validate_cuda_dependencies() -> bool:
    """
    Validate CUDA-dependent extensions at application startup.
    
    This should be called at the very beginning of your application,
    before importing any CUDA-dependent code.
    
    Returns:
        bool: True if all dependencies are working
        
    Raises:
        RuntimeError: If pure PyTorch correlation fails to install

    Design patterns:
    - Fail fast: Validate at startup, not during processing
    - Clear errors: Provide actionable error messages
    - Pure PyTorch: No C++ compilation, works everywhere
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


    # Pure PyTorch correlation is now the DEFAULT and ONLY supported option
    # spatial-correlation-sampler C++ extension is DEPRECATED and REMOVED
    logger.info("=" * 80)
    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] STARTUP: Installing pure PyTorch correlation...")
    logger.info("=" * 80)
    
    try:
        from src.infrastructure.inpainting.pure_pytorch_correlation import install_pure_pytorch_correlation
        install_pure_pytorch_correlation()
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Pure PyTorch correlation installed")
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] No C++ compilation needed - works on all GPUs!")
        logger.info("=" * 80)
        return True

    except Exception as e:
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to install pure PyTorch correlation: {e}")
        logger.error("")
        logger.error("=" * 80)
        logger.error("CRITICAL: Pure PyTorch correlation failed to install")
        logger.error("=" * 80)
        logger.error("")
        logger.error("This is unexpected - pure PyTorch should always work.")
        logger.error("Please check:")
        logger.error("  1. PyTorch is installed: pip list | grep torch")
        logger.error("  2. Code is deployed correctly")
        logger.error("  3. Python version is 3.8+")
        logger.error("")
        logger.error("=" * 80)
        raise RuntimeError(f"Pure PyTorch correlation installation failed: {e}")


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
    validate_propainter_raft: bool = True
) -> None:
    """
    Run all startup validation checks.
    
    Call this at the very beginning of your application.
    
    Args:
        validate_cuda: Whether to validate CUDA dependencies (pure PyTorch)
        validate_propainter_raft: Whether to validate ProPainter RAFT

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
        validate_cuda_dependencies()
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

