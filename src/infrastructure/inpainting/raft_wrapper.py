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
import logging
from pathlib import Path
from typing import Optional, Tuple
import torch

logger = logging.getLogger(__name__)


class SpatialCorrelationSamplerError(RuntimeError):
    """Raised when spatial-correlation-sampler is not working correctly."""
    pass


class CUDAExtensionRebuiltError(RuntimeError):
    """
    Raised when CUDA extension was successfully rebuilt but Python process needs restart.

    The calling code should catch this and exit with code 42 to signal that
    the process should be restarted (by wrapper, supervisor, or manually).

    Exit code 42 = "CUDA extension rebuilt, restart needed"
    """
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
    
    This rebuilds the C++ CUDA extension that ProPainter RAFT uses.
    ProPainter doesn't have its own RAFT/core/correlation extension,
    it only uses the pip package spatial-correlation-sampler.

    Returns:
        bool: True if rebuild succeeded
        
    Design pattern: Fail fast with clear error messages
    """
    import time
    from datetime import datetime

    start_time = time.time()
    logger.warning("=" * 80)
    logger.warning(f"[{datetime.now().strftime('%H:%M:%S')}] 🔧 Starting CUDA extension rebuild...")
    logger.warning("=" * 80)
    logger.warning("This takes ~60-180 seconds depending on GPU architecture")
    logger.warning("Please wait - the system is compiling C++ code...")
    logger.warning("")

    try:
        # Get CUDA version
        if not torch.cuda.is_available():
            logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ CUDA not available - cannot rebuild extension")
            return False
            
        cuda_version = torch.version.cuda
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] 📋 PyTorch CUDA version: {cuda_version}")
        logger.info("")

        # Step 1: Uninstall existing version
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Step 1/3: Uninstalling old version...")
        uninstall_result = subprocess.run(
            ["pip", "uninstall", "-y", "spatial-correlation-sampler"],
            capture_output=True,
            check=False
        )
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Old version uninstalled")
        logger.info("")

        # Step 2: Rebuild from source with compilation
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Step 2/3: Compiling CUDA extension from source...")
        logger.info("⏳ This is the longest step - please be patient...")
        logger.info("💡 The system is downloading source code, compiling C++ with nvcc, and linking CUDA libraries")
        logger.info("")

        compile_start = time.time()
        result = subprocess.run(
            ["pip", "install", "--no-cache-dir", "--force-reinstall", 
             "--no-binary", "spatial-correlation-sampler", 
             "spatial-correlation-sampler", "-v"],  # -v for verbose output
            capture_output=False,  # Show output in real-time
            text=True,
            timeout=300  # 5 minutes max for compilation
        )
        
        compile_elapsed = time.time() - compile_start
        logger.info("")
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱️  Compilation took {compile_elapsed:.1f} seconds")

        if result.returncode != 0:
            logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ spatial-correlation-sampler rebuild failed!")
            logger.error(f"Exit code: {result.returncode}")
            return False

        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Compilation successful")
        logger.info("")

        # Step 3: Note about Python process restart
        # CRITICAL: Python has already loaded the old .so file into memory
        # The new compiled extension won't be used until Python restarts
        total_elapsed = time.time() - start_time
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Step 3/3: Extension rebuilt successfully")
        logger.info("")
        logger.warning("=" * 80)
        logger.warning(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ REBUILD COMPLETE in {total_elapsed:.1f} seconds")
        logger.warning("=" * 80)
        logger.warning("")
        logger.warning("⚠️  IMPORTANT: Python process must RESTART to use new extension")
        logger.warning("   The current Python process has old .so file in memory")
        logger.warning("   Raising exception to trigger restart...")
        logger.warning("")

        # Raise special exception instead of sys.exit(42)
        # This allows main() to catch it and return exit code 42 properly
        raise CUDAExtensionRebuiltError(
            "CUDA extension rebuilt successfully. "
            "Python process must restart to load new extension. "
            "Exit with code 42 to signal restart needed."
        )

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Rebuild timeout after {elapsed:.1f} seconds (max 300s)")
        logger.error("Compilation took too long - this may indicate:")
        logger.error("  - Insufficient CPU/RAM resources")
        logger.error("  - Network issues downloading dependencies")
        logger.error("  - Complex multi-architecture compilation")
        return False
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Unexpected error after {elapsed:.1f} seconds: {e}")
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

            # Create instance with dummy args (RAFT requires args parameter)
            logger.info("Initializing ProPainter RAFT...")

            # RAFT.__init__() requires args parameter
            # Create dummy args with default values
            import argparse
            dummy_args = argparse.Namespace(
                small=False,              # Use full model (not small)
                mixed_precision=False,    # No mixed precision
                alternate_corr=False      # Use standard correlation
            )

            self._raft = RAFT(dummy_args)  # Pass args to avoid TypeError
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
    'CUDAExtensionRebuiltError',  # New exception for rebuild success + restart needed
    'get_raft_wrapper',
    'validate_raft_availability',
    'check_spatial_correlation_sampler',
    'rebuild_spatial_correlation_sampler',
]

