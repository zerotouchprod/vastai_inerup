#!/usr/bin/env python3
"""
Prepare RunPod Network Volume with ML models.

This script downloads models from HuggingFace Hub and saves them to
/runpod-volume/models/ for use with RunPod Serverless.

Usage:
    python prepare_runpod_volume.py

Requirements:
    pip install huggingface_hub
"""

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

# Add src to path for logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from huggingface_hub import snapshot_download, hf_hub_download
    from huggingface_hub.utils import HfHubHTTPError
except ImportError:
    print("ERROR: huggingface_hub not installed. Install with: pip install huggingface_hub")
    sys.exit(1)

try:
    from src.shared.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)


# Configuration
VOLUME_BASE = "/runpod-volume"
MODELS_DIR = Path(VOLUME_BASE) / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Model specifications
MODELS = [
    {
        "name": "dreamshaper-xl-lightning",
        "repo_id": "Lykon/dreamshaper-xl-lightning",
        "type": "file",  # Single file download
        "filename": "dreamshaperXL_lightningDPMSDE.safetensors",
        "ignore_patterns": ["*.bin", "*.onnx", "fp32/*", "*.ckpt", "*.msgpack", "*.h5", "*.ot"],
        "description": "DreamShaper XL Lightning - Text-to-Image model (~2GB)"
    },
    {
        "name": "CogVideoX-5b-I2V",
        "repo_id": "THUDM/CogVideoX-5b",
        "type": "folder",  # Full folder download
        "ignore_patterns": ["*.bin", "*.onnx", "fp32/*", "*.ckpt", "*.msgpack", "*.h5", "*.ot"],
        "description": "CogVideoX-5b Image-to-Video model (~15GB)"
    }
]


def download_model(model_spec: dict) -> bool:
    """
    Download a model from HuggingFace Hub.
    
    Args:
        model_spec: Model specification dictionary
        
    Returns:
        True if successful, False otherwise
    """
    model_name = model_spec["name"]
    repo_id = model_spec["repo_id"]
    model_dir = MODELS_DIR / model_name
    
    logger.info(f"📥 Downloading {model_spec['description']}")
    logger.info(f"  Repository: {repo_id}")
    logger.info(f"  Target: {model_dir}")
    
    try:
        start_time = time.time()
        
        if model_spec["type"] == "file":
            # Download single file
            logger.info(f"  Downloading file: {model_spec['filename']}")
            
            hf_hub_download(
                repo_id=repo_id,
                filename=model_spec["filename"],
                local_dir=model_dir,
                local_dir_use_symlinks=False,
                resume_download=True
            )
            
            # Verify download
            downloaded_file = model_dir / model_spec["filename"]
            if downloaded_file.exists():
                size_mb = downloaded_file.stat().st_size / (1024**2)
                logger.info(f"  ✅ File downloaded: {downloaded_file.name} ({size_mb:.1f} MB)")
            else:
                logger.error(f"  ❌ File not found after download: {model_spec['filename']}")
                return False
                
        else:  # folder download
            # Download entire repository (excluding patterns)
            logger.info(f"  Downloading repository (excluding: {model_spec['ignore_patterns']})")
            
            snapshot_download(
                repo_id=repo_id,
                local_dir=model_dir,
                local_dir_use_symlinks=False,
                ignore_patterns=model_spec["ignore_patterns"],
                resume_download=True
            )
            
            # Verify download
            if model_dir.exists():
                files = list(model_dir.rglob("*"))
                files = [f for f in files if f.is_file()]
                total_size = sum(f.stat().st_size for f in files)
                
                logger.info(f"  ✅ Repository downloaded")
                logger.info(f"    Files: {len(files)}")
                logger.info(f"    Total size: {total_size / (1024**3):.2f} GB")
            else:
                logger.error(f"  ❌ Directory not created: {model_dir}")
                return False
        
        download_time = time.time() - start_time
        logger.info(f"  ⏱️  Download time: {download_time/60:.1f} minutes")
        
        return True
        
    except HfHubHTTPError as e:
        logger.error(f"  ❌ HTTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"  ❌ Unexpected error: {e}")
        return False


def check_disk_space() -> bool:
    """
    Check if there's enough disk space on the volume.
    
    Returns:
        True if sufficient space, False otherwise
    """
    try:
        import shutil
        total, used, free = shutil.disk_usage(VOLUME_BASE)
        
        free_gb = free / (1024**3)
        logger.info(f"💾 Disk space on {VOLUME_BASE}:")
        logger.info(f"  Total: {total / (1024**3):.1f} GB")
        logger.info(f"  Used: {used / (1024**3):.1f} GB")
        logger.info(f"  Free: {free_gb:.1f} GB")
        
        # Estimated required space: ~20GB for both models
        required_gb = 20
        if free_gb < required_gb:
            logger.warning(f"  ⚠️  Warning: Only {free_gb:.1f} GB free, {required_gb} GB recommended")
            return False
            
        return True
        
    except Exception as e:
        logger.warning(f"  ⚠️  Could not check disk space: {e}")
        return True  # Continue anyway


def main():
    """Main function to prepare RunPod Network Volume."""
    logger.info("=" * 60)
    logger.info("RunPod Network Volume Preparation")
    logger.info("=" * 60)
    logger.info(f"Volume path: {VOLUME_BASE}")
    logger.info(f"Models directory: {MODELS_DIR}")
    
    # Check disk space
    if not check_disk_space():
        logger.warning("Continuing despite low disk space...")
    
    # Create models directory
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Created directory: {MODELS_DIR}")
    
    # Download models
    success_count = 0
    total_count = len(MODELS)
    
    for i, model_spec in enumerate(MODELS, 1):
        logger.info("")
        logger.info(f"Model {i}/{total_count}: {model_spec['name']}")
        logger.info("-" * 40)
        
        if download_model(model_spec):
            success_count += 1
        else:
            logger.error(f"Failed to download {model_spec['name']}")
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Successful: {success_count}/{total_count}")
    
    if success_count == total_count:
        logger.info("✅ All models downloaded successfully!")
        
        # List downloaded models
        logger.info("")
        logger.info("Downloaded models:")
        for model_dir in MODELS_DIR.iterdir():
            if model_dir.is_dir():
                files = list(model_dir.rglob("*"))
                files = [f for f in files if f.is_file()]
                total_size = sum(f.stat().st_size for f in files)
                logger.info(f"  📁 {model_dir.name}: {len(files)} files, {total_size / (1024**3):.2f} GB")
    else:
        logger.error("❌ Some models failed to download")
        sys.exit(1)
    
    logger.info("")
    logger.info("🎉 Network Volume is ready for RunPod Serverless!")
    logger.info(f"Models available at: {MODELS_DIR}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()