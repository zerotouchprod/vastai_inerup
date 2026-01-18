"""
GPU availability checking utilities.
Used to enforce GPU requirement for compute-intensive operations.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def check_gpu_available() -> bool:
    """
    Check if CUDA-capable GPU is available.

    Returns:
        True if GPU is available, False otherwise
    """
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        logger.warning("PyTorch not installed, GPU check failed")
        return False


def get_gpu_info() -> Optional[Dict[str, any]]:
    """
    Get detailed GPU information for logging.

    Returns:
        Dictionary with GPU info or None if GPU not available
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return None

        device_count = torch.cuda.device_count()
        current_device = torch.cuda.current_device()
        device_name = torch.cuda.get_device_name(current_device)

        # Get memory info
        memory_allocated = torch.cuda.memory_allocated(current_device) / (1024**3)  # GB
        memory_reserved = torch.cuda.memory_reserved(current_device) / (1024**3)    # GB

        try:
            total_memory = torch.cuda.get_device_properties(current_device).total_memory / (1024**3)  # GB
        except:
            total_memory = None

        return {
            'available': True,
            'device_count': device_count,
            'current_device': current_device,
            'device_name': device_name,
            'memory_allocated_gb': round(memory_allocated, 2),
            'memory_reserved_gb': round(memory_reserved, 2),
            'total_memory_gb': round(total_memory, 2) if total_memory else None,
            'cuda_version': torch.version.cuda,
            'pytorch_version': torch.__version__
        }
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"Failed to get GPU info: {e}")
        return {'available': False, 'error': str(e)}


def require_gpu(operation_name: str) -> None:
    """
    Check if GPU is available and raise GPURequiredError if not.
    Can be bypassed with FORCE_CPU environment variable or AppConfig.

    Args:
        operation_name: Name of the operation requiring GPU (for error message)

    Raises:
        GPURequiredError: If GPU is not available and FORCE_CPU is not set
    """
    from src.domain.exceptions import GPURequiredError
    import os

    # Check if CPU fallback is forced via environment variable
    force_cpu_env = os.environ.get('FORCE_CPU', '').lower() in ('1', 'true', 'yes', 'on')
    
    # Check if CPU fallback is forced via AppConfig
    force_cpu_config = False
    try:
        from src.core.config import get_config
        config = get_config()
        force_cpu_config = getattr(config, 'FORCE_CPU', False)
    except ImportError:
        pass
    
    force_cpu = force_cpu_env or force_cpu_config
    
    if not check_gpu_available():
        if force_cpu:
            source = "AppConfig" if force_cpu_config else "environment variable"
            logger.warning(f"⚠️  GPU not available for {operation_name}, using CPU (slow mode)")
            logger.warning(f"   CPU processing is enabled via {source}")
            logger.warning(f"   This will be extremely slow (hours for typical videos)")
            return
        
        error_msg = (
            f"❌ GPU required for {operation_name}\n"
            f"CPU processing is disabled (too slow, would take hours).\n"
            f"Please run on GPU-enabled instance with CUDA support.\n"
            f"To force CPU processing (very slow), set FORCE_CPU=1 or FORCE_CPU=true in .env"
        )
        logger.error(error_msg)
        raise GPURequiredError(error_msg)

    # Log GPU info
    gpu_info = get_gpu_info()
    if gpu_info:
        logger.info(f"✅ GPU available for {operation_name}: {gpu_info['device_name']}")
        if gpu_info.get('total_memory_gb'):
            logger.info(f"   VRAM: {gpu_info['memory_allocated_gb']:.2f}GB / {gpu_info['total_memory_gb']:.2f}GB")
    else:
        logger.info(f"✅ GPU available for {operation_name}")


def log_gpu_status() -> None:
    """Log current GPU status for diagnostics."""
    gpu_info = get_gpu_info()

    if gpu_info and gpu_info.get('available'):
        logger.info("=== GPU Status ===")
        logger.info(f"  Device: {gpu_info.get('device_name', 'Unknown')}")
        logger.info(f"  CUDA Version: {gpu_info.get('cuda_version', 'Unknown')}")
        logger.info(f"  PyTorch Version: {gpu_info.get('pytorch_version', 'Unknown')}")

        if gpu_info.get('total_memory_gb'):
            alloc = gpu_info.get('memory_allocated_gb', 0)
            total = gpu_info.get('total_memory_gb', 0)
            logger.info(f"  Memory: {alloc:.2f}GB / {total:.2f}GB ({alloc/total*100:.1f}% used)")
    else:
        logger.warning("⚠️  No GPU detected")
        logger.warning("   Some operations may be unavailable or extremely slow")
