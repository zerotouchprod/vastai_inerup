#!/usr/bin/env python3
"""
Test script for ResolutionCalculator logic.
"""
import sys
sys.path.insert(0, '.')

from src.core.config import get_config
from src.infrastructure.inpainting.components.resolution import ResolutionCalculator

def test_resolution_logic():
    config = get_config()
    calculator = ResolutionCalculator(config)
    
    test_cases = [
        # (width, height, vram_gb, description)
        (1920, 1080, 24.0, "1080p with 24GB VRAM"),
        (1920, 1080, 8.0, "1080p with 8GB VRAM"),
        (1920, 1080, 6.0, "1080p with 6GB VRAM (critically low)"),
        (3840, 2160, 24.0, "4K with 24GB VRAM"),
        (3840, 2160, 12.0, "4K with 12GB VRAM"),
        (1280, 720, 8.0, "720p with 8GB VRAM"),
    ]
    
    print("Testing ResolutionCalculator with new logic:")
    print("=" * 80)
    
    for width, height, vram_gb, desc in test_cases:
        print(f"\nTest: {desc}")
        print(f"  Input: {width}x{height}, VRAM: {vram_gb}GB")
        
        target_width, target_height, chunk_size = calculator.calculate_optimal_params(
            width, height, vram_gb
        )
        
        print(f"  Output: {target_width}x{target_height}, chunk size: {chunk_size}")
        
        # Check if native resolution is preserved for 1080p
        original_mp = (width * height) / 1_000_000
        is_1080p_like = original_mp <= 2.5
        vram_critically_low = vram_gb < 8.0
        
        if is_1080p_like and not vram_critically_low:
            print(f"  → 1080p-like video, VRAM not critically low")
            print(f"  → Expected: native resolution preserved")
            if target_width == width and target_height == height:
                print(f"  ✓ PASS: Native resolution preserved")
            else:
                print(f"  ✗ FAIL: Native resolution not preserved")
        else:
            print(f"  → Not 1080p-like or VRAM critically low, downscaling allowed")

if __name__ == "__main__":
    test_resolution_logic()
