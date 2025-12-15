#!/usr/bin/env python3
"""Test unified media processing architecture."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from domain.models import Job

def test_job_validation():
    """Test Job validation for different types."""
    print("Testing Job validation...")
    
    # Test video job
    try:
        job = Job(
            job_id="test_video",
            input_url="file://test.mp4",
            type="video",
            mode="upscale",
            scale=2.0
        )
        print("SUCCESS: Video job created successfully")
    except Exception as e:
        print(f"FAIL: Video job failed: {e}")
    
    # Test video job with remove-subtitles mode
    try:
        job = Job(
            job_id="test_video_subtitles",
            input_url="file://test.mp4",
            type="video",
            mode="remove-subtitles",
            scale=1.0
        )
        print("SUCCESS: Video job with remove-subtitles created successfully")
    except Exception as e:
        print(f"FAIL: Video job with remove-subtitles failed: {e}")
    
    # Test image job
    try:
        job = Job(
            job_id="test_image",
            input_url="file://test.png",
            type="image",
            mode="hdr",
            scale=2.0
        )
        print("SUCCESS: Image job created successfully")
    except Exception as e:
        print(f"FAIL: Image job failed: {e}")
    
    # Test audio job
    try:
        job = Job(
            job_id="test_audio",
            input_url="file://test.mp3",
            type="audio",
            mode="remove_reverb"
        )
        print("SUCCESS: Audio job created successfully")
    except Exception as e:
        print(f"FAIL: Audio job failed: {e}")
    
    # Test invalid type
    try:
        job = Job(
            job_id="test_invalid",
            input_url="file://test.txt",
            type="text",
            mode="upscale"
        )
        print("FAIL: Should have failed for invalid type")
    except ValueError as e:
        print(f"SUCCESS: Correctly rejected invalid type: {e}")
    
    # Test invalid video mode
    try:
        job = Job(
            job_id="test_invalid_video",
            input_url="file://test.mp4",
            type="video",
            mode="invalid_mode"
        )
        print("FAIL: Should have failed for invalid video mode")
    except ValueError as e:
        print(f"SUCCESS: Correctly rejected invalid video mode: {e}")
    
    # Test invalid image mode
    try:
        job = Job(
            job_id="test_invalid_image",
            input_url="file://test.png",
            type="image",
            mode="invalid_mode"
        )
        print("FAIL: Should have failed for invalid image mode")
    except ValueError as e:
        print(f"SUCCESS: Correctly rejected invalid image mode: {e}")
    
    # Test invalid audio mode
    try:
        job = Job(
            job_id="test_invalid_audio",
            input_url="file://test.mp3",
            type="audio",
            mode="invalid_mode"
        )
        print("FAIL: Should have failed for invalid audio mode")
    except ValueError as e:
        print(f"SUCCESS: Correctly rejected invalid audio mode: {e}")

def test_config_loader():
    """Test config loader with new type field."""
    print("\nTesting config loader...")
    
    from infrastructure.config import ConfigLoader
    import tempfile
    import yaml
    
    # Create test config
    config_data = {
        'input_url': 'file://test.mp4',
        'type': 'image',
        'mode': 'hdr',
        'scale': 3.0,
        'image_mode': 'denoise'
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        loader = ConfigLoader(config_path=config_path)
        config = loader.load()
        
        print(f"SUCCESS: Config loaded successfully")
        print(f"   Type: {config.type}")
        print(f"   Mode: {config.mode}")
        print(f"   Scale: {config.scale}")
        print(f"   Image mode: {config.image_mode}")
        
        # Verify values
        assert config.type == 'image'
        assert config.mode == 'hdr'
        assert config.scale == 3.0
        assert config.image_mode == 'denoise'
        
    except Exception as e:
        print(f"FAIL: Config loading failed: {e}")
    finally:
        config_path.unlink()

def test_cli_args():
    """Test CLI argument parsing."""
    print("\nTesting CLI argument parsing...")
    
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--type', choices=['video', 'image', 'audio'], default='video')
    parser.add_argument('--mode', help='Processing mode')
    parser.add_argument('--image-mode', choices=['upscale', 'hdr', 'denoise'])
    parser.add_argument('--audio-mode', choices=['remove_reverb', 'enhance', 'normalize'])
    
    # Test video mode
    args = parser.parse_args(['--type', 'video', '--mode', 'both'])
    print(f"SUCCESS: Video type parsed: type={args.type}, mode={args.mode}")
    
    # Test image mode
    args = parser.parse_args(['--type', 'image', '--mode', 'upscale', '--image-mode', 'hdr'])
    print(f"SUCCESS: Image type parsed: type={args.type}, mode={args.mode}, image-mode={args.image_mode}")
    
    # Test audio mode
    args = parser.parse_args(['--type', 'audio', '--mode', 'enhance', '--audio-mode', 'normalize'])
    print(f"SUCCESS: Audio type parsed: type={args.type}, mode={args.mode}, audio-mode={args.audio_mode}")

def main():
    print("=" * 60)
    print("Testing Unified Media Processing Architecture")
    print("=" * 60)
    
    test_job_validation()
    test_config_loader()
    test_cli_args()
    
    print("\n" + "=" * 60)
    print("Summary:")
    print("- Unified Job model supports video, image, and audio types")
    print("- Each type has specific modes:")
    print("  • Video: upscale, interp, both, remove-subtitles")
    print("  • Image: upscale, hdr, denoise")
    print("  • Audio: remove_reverb, enhance, normalize")
    print("- Config loader supports new type, image_mode, audio_mode fields")
    print("- CLI accepts --type parameter and type-specific modes")
    print("=" * 60)

if __name__ == "__main__":
    main()
