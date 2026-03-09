#!/usr/bin/env python3
"""
Script to upload models to RunPod Network Volume
Run this on a pod with mounted network volume
"""

import os
import sys
import time
from pathlib import Path
from huggingface_hub import hf_hub_download, snapshot_download

def main():
    print("=" * 60)
    print("Uploading models to RunPod Network Volume")
    print("=" * 60)
    
    # Base paths
    volume_path = Path("/runpod-volume")
    models_path = volume_path / "models"
    
    # Create directories
    dreamshaper_path = models_path / "dreamshaper-xl-lightning"
    cogvideox_path = models_path / "CogVideoX-5b-I2V"
    
    dreamshaper_path.mkdir(parents=True, exist_ok=True)
    cogvideox_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Volume path: {volume_path}")
    print(f"Models path: {models_path}")
    print(f"DreamShaper path: {dreamshaper_path}")
    print(f"CogVideoX path: {cogvideox_path}")
    
    # Check disk space
    total, used, free = os.popen(f"df -h {volume_path}").read().split('\n')[1].split()
    print(f"\n📊 Disk space on {volume_path}:")
    print(f"  Total: {total}, Used: {used}, Free: {free}")
    
    # 1. Download DreamShaper XL Lightning
    print("\n" + "=" * 60)
    print("1. Downloading DreamShaper XL Lightning")
    print("=" * 60)
    
    dreamshaper_file = dreamshaper_path / "sdxl_lightning_4step_unet.safetensors"
    
    if dreamshaper_file.exists():
        size_mb = dreamshaper_file.stat().st_size / (1024 * 1024)
        print(f"✅ DreamShaper already exists: {dreamshaper_file}")
        print(f"   Size: {size_mb:.2f} MB")
    else:
        print(f"Downloading DreamShaper to: {dreamshaper_path}")
        try:
            start_time = time.time()
            hf_hub_download(
                repo_id="ByteDance/SDXL-Lightning",
                filename="sdxl_lightning_4step_unet.safetensors",
                local_dir=dreamshaper_path,
                local_dir_use_symlinks=False
            )
            download_time = time.time() - start_time
            size_mb = dreamshaper_file.stat().st_size / (1024 * 1024)
            print(f"✅ DreamShaper downloaded successfully!")
            print(f"   Size: {size_mb:.2f} MB")
            print(f"   Time: {download_time:.2f} seconds")
            print(f"   Speed: {size_mb/download_time:.2f} MB/s")
        except Exception as e:
            print(f"❌ Error downloading DreamShaper: {e}")
            return 1
    
    # 2. Download CogVideoX-5b-I2V
    print("\n" + "=" * 60)
    print("2. Downloading CogVideoX-5b-I2V")
    print("=" * 60)
    
    # Check if CogVideoX already exists
    cogvideox_files = list(cogvideox_path.glob("*"))
    if cogvideox_files:
        total_size = sum(f.stat().st_size for f in cogvideox_files if f.is_file())
        total_size_gb = total_size / (1024**3)
        print(f"✅ CogVideoX directory already contains {len(cogvideox_files)} files")
        print(f"   Total size: {total_size_gb:.2f} GB")
        print("   First 10 files:")
        for f in cogvideox_files[:10]:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"     - {f.name} ({size_mb:.2f} MB)")
    else:
        print(f"Downloading CogVideoX to: {cogvideox_path}")
        print("Note: This is a large model (~15GB), may take 30-60 minutes...")
        
        try:
            start_time = time.time()
            snapshot_download(
                repo_id="THUDM/CogVideoX-5b",
                local_dir=cogvideox_path,
                local_dir_use_symlinks=False,
                ignore_patterns=["*.bin", "*.msgpack", "*.h5", "*.ot"],  # Skip large binary files
                resume_download=True
            )
            download_time = time.time() - start_time
            
            # Count downloaded files
            downloaded_files = list(cogvideox_path.glob("*"))
            total_size = sum(f.stat().st_size for f in downloaded_files if f.is_file())
            total_size_gb = total_size / (1024**3)
            
            print(f"✅ CogVideoX downloaded successfully!")
            print(f"   Files: {len(downloaded_files)}")
            print(f"   Total size: {total_size_gb:.2f} GB")
            print(f"   Time: {download_time/60:.2f} minutes")
            print(f"   Speed: {total_size_gb/(download_time/3600):.2f} GB/hour")
            
            print("\n   First 10 downloaded files:")
            for f in downloaded_files[:10]:
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"     - {f.name} ({size_mb:.2f} MB)")
                
        except Exception as e:
            print(f"❌ Error downloading CogVideoX: {e}")
            return 1
    
    # Final summary
    print("\n" + "=" * 60)
    print("📦 Download Summary")
    print("=" * 60)
    
    # DreamShaper size
    dreamshaper_size = dreamshaper_file.stat().st_size / (1024**3) if dreamshaper_file.exists() else 0
    
    # CogVideoX size
    cogvideox_files = list(cogvideox_path.glob("*"))
    cogvideox_size = sum(f.stat().st_size for f in cogvideox_files if f.is_file()) / (1024**3)
    
    total_size = dreamshaper_size + cogvideox_size
    
    print(f"DreamShaper XL Lightning: {dreamshaper_size:.2f} GB")
    print(f"CogVideoX-5b-I2V: {cogvideox_size:.2f} GB")
    print(f"Total models size: {total_size:.2f} GB")
    
    # Check remaining space
    total, used, free = os.popen(f"df -h {volume_path}").read().split('\n')[1].split()
    print(f"\n📊 Final disk space on {volume_path}:")
    print(f"  Total: {total}, Used: {used}, Free: {free}")
    
    print("\n✅ All models uploaded to RunPod Network Volume!")
    print("   You can now deploy the serverless handler.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())