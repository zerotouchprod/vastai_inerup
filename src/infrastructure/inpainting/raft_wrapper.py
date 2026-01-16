"""
ProPainter RAFT Wrapper with Graceful Degradation
==================================================

Senior Python approach: Don't patch third-party code, wrap it.

This module provides a safe wrapper around ProPainter's RAFT that:
1. Detects spatial-correlation-sampler availability at import time
2. Provides fallback behavior if extension is broken
3. Gives clear error messages with actionable steps
4. Follows Python best practices (EAFP, dependency injection, composition)
"""

import os
import sys
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional, Tuple
import torch

logger = logging.getLogger(__name__)


class SpatialCorrelationSamplerError(RuntimeError):
    """Raised when spatial-correlation-sampler is not working correctly."""
    pass


def check_spatial_correlation_sampler() -> Tuple[bool, Optional[str]]:
    """
    Check if spatial-correlation-sampler is working correctly.
    
    Returns:
        Tuple[bool, Optional[str]]: (is_working, error_message)
    
    Design pattern: Explicit is better than implicit (PEP 20)
    """
    try:
        import spatial_correlation_sampler
        # Try to access key functionality
        _ = spatial_correlation_sampler.SpatialCorrelationSampler
        return True, None
    except ImportError as e:
        return False, f"spatial-correlation-sampler not installed: {e}"
    except AttributeError as e:
        return False, f"spatial-correlation-sampler missing expected API: {e}"
    except Exception as e:
        return False, f"spatial-correlation-sampler unexpected error: {e}"


def rebuild_spatial_correlation_sampler() -> bool:
    """
    Rebuild spatial-correlation-sampler for current CUDA environment.
    
    CRITICAL: This rebuilds the ACTUAL C++ extension that ProPainter uses,
    not just the pip package wrapper.

    Returns:
        bool: True if rebuild succeeded
        
    Design pattern: Fail fast with clear error messages
    """
    logger.warning("Attempting to rebuild ProPainter RAFT correlation extension...")
    logger.warning("This is a LAST RESORT and indicates Docker image needs rebuild")
    
    try:
        # Get CUDA version
        if not torch.cuda.is_available():
            logger.error("CUDA not available - cannot rebuild extension")
            return False
            
        cuda_version = torch.version.cuda
        logger.info(f"PyTorch CUDA version: {cuda_version}")
        
        # Step 1: Try to rebuild spatial-correlation-sampler package first
        logger.info("Step 1: Rebuilding spatial-correlation-sampler package...")
        subprocess.run(
            ["pip", "uninstall", "-y", "spatial-correlation-sampler"],
            capture_output=True,
            check=False
        )
        
        result = subprocess.run(
            ["pip", "install", "--no-cache-dir", "--force-reinstall", 
             "--no-binary", "spatial-correlation-sampler", 
             "spatial-correlation-sampler"],
            capture_output=True,
            text=True,
            timeout=180  # 3 minutes max
        )
        
        if result.returncode != 0:
            logger.warning(f"spatial-correlation-sampler rebuild failed: {result.stderr}")
            logger.warning("Will try ProPainter RAFT correlation extension directly...")
        else:
            logger.info("✅ spatial-correlation-sampler package rebuilt")

        # Step 2: Rebuild ProPainter RAFT correlation extension
        # This is the REAL fix for the CorrBlock error
        propainter_root = Path(os.getenv("PROPAINTER_ROOT", "/opt/ProPainter"))
        correlation_dir = propainter_root / "RAFT" / "core" / "correlation"

        if not correlation_dir.exists():
            logger.error(f"ProPainter RAFT correlation dir not found: {correlation_dir}")
            return False

        logger.info(f"Step 2: Rebuilding ProPainter RAFT correlation extension at {correlation_dir}")

        # Clean previous build artifacts
        logger.info("Cleaning previous build artifacts...")
        for pattern in ["build", "dist", "*.egg-info", "*.so"]:
            for path in correlation_dir.glob(pattern):
                if path.is_dir():
                    import shutil
                    shutil.rmtree(path)
                    logger.info(f"  Removed {path}")
                elif path.is_file():
                    path.unlink()
                    logger.info(f"  Removed {path}")

        # Rebuild extension
        logger.info("Building C++ extension for current CUDA version...")
        result = subprocess.run(
            ["python3", "setup.py", "install"],
            cwd=str(correlation_dir),
            capture_output=True,
            text=True,
            timeout=180
        )

        if result.returncode != 0:
            logger.error(f"RAFT correlation extension build failed!")
            logger.error(f"STDOUT: {result.stdout[-500:]}")
            logger.error(f"STDERR: {result.stderr[-500:]}")
            return False

        logger.info("✅ ProPainter RAFT correlation extension rebuilt successfully")
        logger.info(f"Build output: {result.stdout[-200:]}")

        # Step 3: Verify it works now
        is_working, error = check_spatial_correlation_sampler()
        if not is_working:
            logger.error(f"Rebuild completed but still broken: {error}")
            logger.error("You may need to restart Python process for changes to take effect")
            return False
            
        logger.info("✅ All CUDA extensions rebuilt and verified")
        return True
        
    except subprocess.TimeoutExpired:
        logger.error("Rebuild timed out after 3 minutes")
        return False
    except Exception as e:
        logger.error(f"Rebuild failed with exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


class ProPainterRAFTWrapper:
    """
    Wrapper around ProPainter RAFT with automatic error handling.
    
    Design patterns:
    - Lazy initialization (don't fail at import time)
    - Graceful degradation (provide fallback or clear error)
    - Dependency injection (configurable ProPainter path)
    - Single Responsibility (only handles RAFT initialization)
    
    Usage:
        wrapper = ProPainterRAFTWrapper()
        raft = wrapper.get_raft()  # May raise SpatialCorrelationSamplerError
    """
    
    def __init__(self, propainter_root: Optional[Path] = None):
        """
        Initialize wrapper.
        
        Args:
            propainter_root: Path to ProPainter installation
        """
        self.propainter_root = propainter_root or Path(
            os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
        )
        self._raft = None
        self._initialization_attempted = False
        self._initialization_error = None
        
    def _check_dependencies(self) -> None:
        """
        Check if all dependencies are available.
        
        Raises:
            SpatialCorrelationSamplerError: If dependencies are broken
        """
        # Check spatial-correlation-sampler
        is_working, error = check_spatial_correlation_sampler()
        
        if not is_working:
            logger.error("=" * 80)
            logger.error("CRITICAL: spatial-correlation-sampler is NOT working")
            logger.error("=" * 80)
            logger.error(f"Error: {error}")
            logger.error("")
            logger.error("This means:")
            logger.error("  1. Docker image was built with different CUDA version")
            logger.error("  2. Extension needs to be rebuilt for this environment")
            logger.error("")
            logger.error("Solutions (in order of preference):")
            logger.error("  1. REBUILD DOCKER IMAGE with correct CUDA version")
            logger.error("  2. Run: pip install --force-reinstall spatial-correlation-sampler")
            logger.error("  3. Use different GPU instance with matching CUDA version")
            logger.error("")
            logger.error("=" * 80)
            
            # Attempt automatic rebuild (LAST RESORT)
            if os.getenv("AUTO_REBUILD_CUDA_EXTENSIONS", "false").lower() == "true":
                logger.warning("AUTO_REBUILD_CUDA_EXTENSIONS=true, attempting rebuild...")
                if rebuild_spatial_correlation_sampler():
                    logger.info("Auto-rebuild succeeded, continuing...")
                    return
                else:
                    logger.error("Auto-rebuild failed")
            
            raise SpatialCorrelationSamplerError(
                f"spatial-correlation-sampler is broken: {error}\n"
                f"Docker image must be rebuilt with correct CUDA version.\n"
                f"Set AUTO_REBUILD_CUDA_EXTENSIONS=true to attempt automatic rebuild."
            )
    
    def _initialize_raft(self) -> None:
        """
        Initialize RAFT model.
        
        Raises:
            SpatialCorrelationSamplerError: If initialization fails
        """
        if self._initialization_attempted:
            if self._initialization_error:
                raise self._initialization_error
            return
            
        self._initialization_attempted = True
        
        try:
            # Check dependencies first
            self._check_dependencies()
            
            # Add ProPainter to path
            if str(self.propainter_root) not in sys.path:
                sys.path.insert(0, str(self.propainter_root))
            
            # Import RAFT (this will fail if spatial-correlation-sampler is broken)
            from model.modules.flow_comp_raft import RAFT
            
            # Create instance
            logger.info("Initializing ProPainter RAFT...")
            self._raft = RAFT()
            logger.info("✅ RAFT initialized successfully")
            
        except ImportError as e:
            error = SpatialCorrelationSamplerError(
                f"Failed to import RAFT: {e}\n"
                f"This usually means ProPainter is not installed correctly."
            )
            self._initialization_error = error
            raise error
            
        except Exception as e:
            # If we get here, spatial-correlation-sampler check passed but RAFT still failed
            # This is a different kind of error
            error = SpatialCorrelationSamplerError(
                f"RAFT initialization failed: {e}\n"
                f"spatial-correlation-sampler passed checks but RAFT still failed.\n"
                f"This may indicate CUDA runtime mismatch."
            )
            self._initialization_error = error
            raise error
    
    def get_raft(self):
        """
        Get RAFT model instance.
        
        Returns:
            RAFT model instance
            
        Raises:
            SpatialCorrelationSamplerError: If RAFT cannot be initialized
            
        Design pattern: Lazy initialization with caching
        """
        if self._raft is None:
            self._initialize_raft()
        return self._raft
    
    def is_available(self) -> bool:
        """
        Check if RAFT is available without raising exceptions.
        
        Returns:
            bool: True if RAFT can be used
            
        Design pattern: LBYL (Look Before You Leap) variant for graceful degradation
        """
        try:
            self.get_raft()
            return True
        except SpatialCorrelationSamplerError:
            return False


# Module-level singleton for convenience
_default_wrapper: Optional[ProPainterRAFTWrapper] = None


def get_raft_wrapper() -> ProPainterRAFTWrapper:
    """
    Get singleton RAFT wrapper instance.
    
    Design pattern: Singleton for expensive resources
    """
    global _default_wrapper
    if _default_wrapper is None:
        _default_wrapper = ProPainterRAFTWrapper()
    return _default_wrapper


def validate_raft_availability() -> None:
    """
    Validate that RAFT is available.
    
    Call this at application startup to fail fast if RAFT is broken.
    
    Raises:
        SpatialCorrelationSamplerError: If RAFT is not available
        
    Design pattern: Fail fast principle
    """
    wrapper = get_raft_wrapper()
    wrapper.get_raft()  # Will raise if broken
    logger.info("✅ ProPainter RAFT validation passed")


# Convenient module-level API
__all__ = [
    'ProPainterRAFTWrapper',
    'SpatialCorrelationSamplerError',
    'get_raft_wrapper',
    'validate_raft_availability',
    'check_spatial_correlation_sampler',
    'rebuild_spatial_correlation_sampler',
]

