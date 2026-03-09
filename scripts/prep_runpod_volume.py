#!/usr/bin/env python3
"""
Script to download models to RunPod Network Volume.

This script should be run ONCE on a temporary pod to populate the Network Volume.
It downloads models directly into /runpod-volume/models/ directory.

Usage:
    python scripts/prep_runpod_volume.py
"""

import os
import sys
import argparse
from pathlib import Path
from huggingface_hub import snapshot_download

# Model configurations
MODELS = {
    "dreamshaper-xl-lightning": {
        "repo_id": "Lykon/dreamshaper-xl-lightning",
        "exclude_patterns": ["*.bin", "*.onnx", "fp32/*", "*.safetensors.index.json"],
        "allow_patterns": ["*.safetensors", "*.json", "*.txt", "*.py"],
    },
    "CogVideoX-5b-I2V": {
        "repo_id": "THUDM/CogVideoX-5b-I2V",
        "exclude_patterns": ["*.bin", "*.onnx", "fp32/*", "*.safetensors.index.json"],
        "allow_patterns": ["*.safetensors", "*.json", "*.txt", "*.py"],
    }
}

def download_model(model_name: str, model_config: dict, output_dir: Path):
    """
    Download a model from Hugging Face Hub.
    
    Args:
        model_name: Name of the model (for logging)
        model_config: Configuration dictionary for the model
        output_dir: Directory to save the model
    """
    print(f"\n{'='*60}")
    print(f"Downloading: {model_name}")
    print(f"Repository: {model_config['repo_id']}")
    print(f"Destination: {output_dir}")
    print(f"{'='*60}")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Download model using snapshot_download
        snapshot_download(
            repo_id=model_config["repo_id"],
            local_dir=output_dir,
            local_dir_use_symlinks=False,  # Copy files instead of symlinks
            ignore_patterns=model_config["exclude_patterns"],
            allow_patterns=model_config["allow_patterns"],
            resume_download=True,
            max_workers=4,
        )
        
        print(f"✅ Successfully downloaded {model_name}")
        
        # List downloaded files
        total_size = 0
        file_count = 0
        for file_path in output_dir.rglob("*"):
            if file_path.is_file():
                file_count += 1
                total_size += file_path.stat().st_size
        
        print(f"   Files: {file_count}")
        print(f"   Size: {total_size / 1024**3:.2f} GB")
        
    except Exception as e:
        print(f"❌ Failed to download {model_name}: {e}")
        raise

def check_disk_space(path: Path):
    """Check available disk space."""
    import shutil
    
    total, used, free = shutil.disk_usage(path)
    print(f"\nDisk space at {path}:")
    print(f"  Total: {total / 1024**3:.2f} GB")
    print(f"  Used: {used / 1024**3:.2f} GB")
    print(f"  Free: {free / 1024**3:.2f} GB")
    
    # Models require ~10-15GB each
    required_space = 30 * 1024**3  # 30GB
    if free < required_space:
        print(f"⚠️  Warning: Only {free / 1024**3:.2f} GB free, models require ~30GB")
        return False
    return True

def verify_downloads(base_dir: Path):
    """Verify that models were downloaded correctly."""
    print(f"\n{'='*60}")
    print("Verifying downloads...")
    print(f"{'='*60}")
    
    for model_name in MODELS.keys():
        model_dir = base_dir / model_name
        if not model_dir.exists():
            print(f"❌ {model_name}: Directory not found")
            continue
        
        # Check for essential files
        essential_extensions = [".safetensors", ".json", ".txt", ".py"]
        files = list(model_dir.rglob("*"))
        
        if not files:
            print(f"❌ {model_name}: No files found")
            continue
        
        # Count files by extension
        safetensors_count = len(list(model_dir.rglob("*.safetensors")))
        json_count = len(list(model_dir.rglob("*.json")))
        
        print(f"✅ {model_name}:")
        print(f"   Total files: {len(files)}")
        print(f"   .safetensors files: {safetensors_count}")
        print(f"   .json files: {json_count}")
        
        # Check for model_index.json (required by diffusers)
        model_index = model_dir / "model_index.json"
        if model_index.exists():
            print(f"   model_index.json: ✓")
        else:
            print(f"   model_index.json: ✗ (may cause issues)")

def main():
    parser = argparse.ArgumentParser(description="Download models to RunPod Network Volume")
    parser.add_argument(
        "--volume-path",
        type=str,
        default="/runpod-volume/models",
        help="Path to RunPod Network Volume (default: /runpod-volume/models)"
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Skip verification step"
    )
    parser.add_argument(
        "--model",
        type=str,
        choices=list(MODELS.keys()) + ["all"],
        default="all",
        help="Specific model to download (default: all)"
    )
    
    args = parser.parse_args()
    
    # Convert to Path object
    volume_path = Path(args.volume_path)
    
    print(f"{'='*60}")
    print("RunPod Network Volume Preparation Script")
    print(f"{'='*60}")
    print(f"Volume path: {volume_path}")
    print(f"Models to download: {args.model}")
    print(f"{'='*60}")
    
    # Check if volume path exists
    if not volume_path.exists():
        print(f"❌ Volume path does not exist: {volume_path}")
        print("Please ensure the RunPod Network Volume is mounted correctly.")
        sys.exit(1)
    
    # Check disk space
    if not check_disk_space(volume_path):
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            print("Aborting.")
            sys.exit(1)
    
    # Determine which models to download
    models_to_download = MODELS if args.model == "all" else {args.model: MODELS[args.model]}
    
    # Download models
    for model_name, model_config in models_to_download.items():
        model_dir = volume_path / model_name
        
        # Skip if already exists
        if model_dir.exists() and list(model_dir.iterdir()):
            print(f"\n⚠️  {model_name} already exists at {model_dir}")
            response = input("Overwrite? (y/N): ")
            if response.lower() != 'y':
                print(f"Skipping {model_name}")
                continue
        
        # Download model
        download_model(model_name, model_config, model_dir)
    
    # Verify downloads
    if not args.skip_verification:
        verify_downloads(volume_path)
    
    print(f"\n{'='*60}")
    print("✅ Volume preparation complete!")
    print(f"{'='*60}")
    print("\nNext steps:")
    print("1. Create a RunPod Serverless function using the Docker image")
    print("2. Mount the network volume at /runpod-volume")
    print("3. Test the function with a simple prompt")
    print("\nExample test input:")
    print(json.dumps({
        "prompt": "A beautiful sunset over mountains",
        "t2i_steps": 4,
        "t2i_guidance_scale": 0.0,
        "num_inference_steps": 25,
        "guidance_scale": 6.0,
        "num_frames": 16,
        "fps": 8
    }, indent=2))

if __name__ == "__main__":
    import json  # Import here to avoid circular import
    main()