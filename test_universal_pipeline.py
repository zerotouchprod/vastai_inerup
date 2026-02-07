#!/usr/bin/env python3
"""
Test script for Universal Image-to-Video Pipeline.
Tests both photorealism and anime generation capabilities.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.services.generation.pipeline import UniversalPipeline


def test_photorealism():
    """Test photorealism generation."""
    print("🧪 Testing photorealism generation...")
    
    pipeline = UniversalPipeline()
    
    # Photorealistic prompt
    prompt = "Cyberpunk city at night, rain, neon lights, realistic photography, 8k"
    negative_prompt = "blurry, cartoon, anime, illustration, painting"
    
    try:
        image_path, video_path = pipeline.run_pipeline(prompt, negative_prompt)
        print(f"✅ Photorealism test passed!")
        print(f"   Image: {image_path}")
        print(f"   Video: {video_path}")
        return True
    except Exception as e:
        print(f"❌ Photorealism test failed: {e}")
        return False


def test_anime():
    """Test anime generation."""
    print("\n🧪 Testing anime generation...")
    
    pipeline = UniversalPipeline()
    
    # Anime prompt
    prompt = "Anime girl running through cherry blossom forest, vibrant colors, studio ghibli style"
    negative_prompt = "realistic, photo, blurry, dark"
    
    try:
        image_path, video_path = pipeline.run_pipeline(prompt, negative_prompt)
        print(f"✅ Anime test passed!")
        print(f"   Image: {image_path}")
        print(f"   Video: {video_path}")
        return True
    except Exception as e:
        print(f"❌ Anime test failed: {e}")
        return False


def test_3d_art():
    """Test 3D art generation."""
    print("\n🧪 Testing 3D art generation...")
    
    pipeline = UniversalPipeline()
    
    # 3D art prompt
    prompt = "Futuristic spaceship, 3D render, cinematic lighting, unreal engine, octane render"
    negative_prompt = "2d, flat, painting, drawing"
    
    try:
        image_path, video_path = pipeline.run_pipeline(prompt, negative_prompt)
        print(f"✅ 3D art test passed!")
        print(f"   Image: {image_path}")
        print(f"   Video: {video_path}")
        return True
    except Exception as e:
        print(f"❌ 3D art test failed: {e}")
        return False


def test_vram_management():
    """Test VRAM management between pipeline steps."""
    print("\n🧪 Testing VRAM management...")
    
    pipeline = UniversalPipeline()
    
    # Check initial VRAM
    if torch.cuda.is_available():
        initial_vram = torch.cuda.memory_allocated()
        print(f"   Initial VRAM: {initial_vram / 1024**3:.2f} GB")
    
    # Run pipeline
    prompt = "Test VRAM management, simple scene"
    
    try:
        image_path, video_path = pipeline.run_pipeline(prompt)
        
        # Check final VRAM
        if torch.cuda.is_available():
            final_vram = torch.cuda.memory_allocated()
            print(f"   Final VRAM: {final_vram / 1024**3:.2f} GB")
            print(f"   VRAM delta: {(final_vram - initial_vram) / 1024**3:.2f} GB")
        
        print(f"✅ VRAM management test passed!")
        return True
    except Exception as e:
        print(f"❌ VRAM management test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("🚀 Universal Pipeline Test Suite")
    print("=" * 50)
    
    # Import torch here to avoid import issues
    import torch
    
    results = []
    
    # Run tests
    results.append(("Photorealism", test_photorealism()))
    results.append(("Anime", test_anime()))
    results.append(("3D Art", test_3d_art()))
    results.append(("VRAM Management", test_vram_management()))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {test_name:20} {status}")
        if success:
            passed += 1
    
    print(f"\n🎯 {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n✨ All tests passed! Universal pipeline is ready.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check logs for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())