#!/usr/bin/env python3
"""
Test script to check RIFE availability in the system.
"""

import sys
import os
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_rife_availability():
    """Check if RIFE is available in the system."""
    
    # Check PyTorch
    try:
        import torch
        logger.info(f"PyTorch available: {torch.__version__}")
        logger.info(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    except ImportError:
        logger.error("PyTorch not available")
        return False
    
    # Check paths
    possible_paths = [
        Path('/opt/rife_models/train_log'),  # Docker container models
        Path('/workspace/project/RIFEv4.26_0921'),  # Preinstalled RIFE
        Path('/workspace/project/external/RIFE'),  # Cloned repo
        Path('/tmp/RIFE'),  # Temporary clone
        Path('RIFEv4.26_0921'),  # Local
        Path('external/RIFE'),  # Local
    ]
    
    logger.info("Checking RIFE paths:")
    for path in possible_paths:
        exists = path.exists()
        has_pkl = list(path.glob('*.pkl')) if exists else []
        logger.info(f"  {path}: exists={exists}, has_pkl={len(has_pkl)}")
        if exists and has_pkl:
            logger.info(f"    Found .pkl files: {[p.name for p in has_pkl[:3]]}")
    
    # Check for RIFE code
    logger.info("\nChecking for RIFE code files:")
    code_paths = [
        Path('/workspace/project/external/RIFE/model/RIFE.py'),
        Path('/workspace/project/RIFEv4.26_0921/model/RIFE.py'),
        Path('/workspace/project/RIFEv4.26_0921/train_log/RIFE_HDv3.py'),
        Path('/tmp/RIFE/model/RIFE.py'),
    ]
    
    for path in code_paths:
        exists = path.exists()
        logger.info(f"  {path}: exists={exists}")
        if exists:
            logger.info(f"    Size: {path.stat().st_size} bytes")
    
    # Try to import RIFE
    logger.info("\nTrying to import RIFE...")
    try:
        # Add possible paths to sys.path
        for path in possible_paths:
            if path.exists():
                sys.path.insert(0, str(path))
                logger.info(f"Added to sys.path: {path}")
        
        # Try to find and import RIFE module
        import importlib.util
        
        # Try different module locations
        module_locations = [
            ('/workspace/project/external/RIFE/model/RIFE.py', 'RIFE_model'),
            ('/workspace/project/RIFEv4.26_0921/model/RIFE.py', 'RIFE_v4'),
            ('/workspace/project/RIFEv4.26_0921/train_log/RIFE_HDv3.py', 'RIFE_HDv3'),
        ]
        
        for module_path, module_name in module_locations:
            if os.path.exists(module_path):
                logger.info(f"Trying to import from {module_path}")
                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if spec is None:
                        logger.warning(f"  Could not create spec for {module_path}")
                        continue
                    
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    
                    # Check for Model class
                    if hasattr(module, 'Model'):
                        logger.info(f"  ✓ Successfully imported {module_name}.Model")
                        return True
                    else:
                        logger.warning(f"  Module {module_name} doesn't have 'Model' class")
                except Exception as e:
                    logger.warning(f"  Failed to import {module_path}: {e}")
        
        logger.error("Could not import RIFE Model class from any location")
        return False
        
    except Exception as e:
        logger.error(f"Error checking RIFE availability: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("Testing RIFE availability")
    success = check_rife_availability()
    if success:
        logger.info("✅ RIFE is available")
        sys.exit(0)
    else:
        logger.error("❌ RIFE is not available")
        sys.exit(1)
