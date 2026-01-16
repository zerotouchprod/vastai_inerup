#!/usr/bin/env python3
"""
Test script for ROI improvements:
1. Bounding box ROI format parsing
2. VRAM-adaptive kernel sizing
3. Debug mode flag
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_roi_parsing():
    """Test ROI parsing with all supported formats."""
    from src.services.cleaner_service import SubtitleRemoverService
    
    print("=" * 60)
    print("TEST 1: ROI Format Parsing")
    print("=" * 60)
    
    # Mock dependencies
    class MockInpainter:
        pass
    
    class MockMaskService:
        pass
    
    test_cases = [
        (None, "percentage", 0.6, "Default (bottom 60%)"),
        ("bottom", "percentage", 0.6, "Preset: bottom"),
        ("top", "percentage", 0.6, "Preset: top"),
        ("full", "percentage", 1.0, "Preset: full"),
        ("0.8", "percentage", 0.8, "Single float (80%)"),
        ("0.05,0.4,0.9,0.6", "bbox", 0.6, "Bounding box x1,y1,x2,y2"),
    ]
    
    for roi_input, expected_mode, expected_factor, description in test_cases:
        try:
            service = SubtitleRemoverService(
                MockMaskService(),
                MockInpainter(),
                lang='en',
                roi_factor=roi_input,
                debug=False
            )
            
            assert service.roi_mode == expected_mode, f"Expected mode {expected_mode}, got {service.roi_mode}"
            assert abs(service.roi_height_factor - expected_factor) < 0.01, \
                f"Expected factor {expected_factor}, got {service.roi_height_factor}"
            
            if roi_input and ',' in str(roi_input):
                assert service.roi_bbox is not None, "Bounding box should be set"
            
            print(f"✅ {description}: PASSED")
            print(f"   Mode: {service.roi_mode}, Factor: {service.roi_height_factor:.2f}")
            if service.roi_bbox:
                print(f"   BBox: {service.roi_bbox}")
        except Exception as e:
            print(f"❌ {description}: FAILED - {e}")
            return False
    
    print("\n✅ All ROI parsing tests PASSED!\n")
    return True


def test_vram_detection():
    """Test VRAM-adaptive kernel sizing."""
    from src.services.cleaner_service import SubtitleRemoverService
    
    print("=" * 60)
    print("TEST 2: VRAM-Adaptive Kernel Sizing")
    print("=" * 60)
    
    class MockInpainter:
        pass
    
    class MockMaskService:
        pass
    
    try:
        service = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='bottom',
            debug=False
        )
        
        kernel_size = service._kernel_size
        assert 30 <= kernel_size <= 45, f"Kernel size {kernel_size} out of expected range [30-45]"
        
        print(f"✅ VRAM detection: PASSED")
        print(f"   Detected kernel size: {kernel_size}x{kernel_size}")
        
        # Try to detect actual VRAM if available
        try:
            import torch
            if torch.cuda.is_available():
                vram_bytes = torch.cuda.get_device_properties(0).total_memory
                vram_gb = vram_bytes / (1024 ** 3)
                print(f"   VRAM: {vram_gb:.1f}GB")
                
                if vram_gb < 8:
                    assert kernel_size == 30, f"Expected 30x30 for <8GB VRAM, got {kernel_size}"
                elif vram_gb < 16:
                    assert kernel_size == 40, f"Expected 40x40 for 8-16GB VRAM, got {kernel_size}"
                else:
                    assert kernel_size == 45, f"Expected 45x45 for >16GB VRAM, got {kernel_size}"
                print(f"   ✅ Kernel size matches VRAM tier")
            else:
                print(f"   ℹ️  CUDA not available, using default kernel size")
        except ImportError:
            print(f"   ℹ️  PyTorch not available for VRAM detection")
        
        print("\n✅ VRAM detection test PASSED!\n")
        return True
    except Exception as e:
        print(f"❌ VRAM detection test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_debug_mode():
    """Test debug mode flag."""
    import os
    from src.services.cleaner_service import SubtitleRemoverService
    
    print("=" * 60)
    print("TEST 3: Debug Mode Flag")
    print("=" * 60)
    
    class MockInpainter:
        pass
    
    class MockMaskService:
        pass
    
    try:
        # Test 1: Debug explicitly off
        service1 = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='bottom',
            debug=False
        )
        assert service1.debug_mode == False, "Debug should be off when explicitly set to False"
        print(f"✅ Debug explicitly off: PASSED")
        
        # Test 2: Debug explicitly on
        service2 = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='bottom',
            debug=True
        )
        assert service2.debug_mode == True, "Debug should be on when explicitly set to True"
        print(f"✅ Debug explicitly on: PASSED")
        
        # Test 3: Debug from env var
        os.environ['DEBUG_SUBTITLE_REMOVAL'] = '1'
        service3 = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='bottom',
            debug=None
        )
        assert service3.debug_mode == True, "Debug should be on when env var is set to '1'"
        print(f"✅ Debug from env var: PASSED")
        
        # Clean up
        os.environ['DEBUG_SUBTITLE_REMOVAL'] = '0'
        
        print("\n✅ All debug mode tests PASSED!\n")
        return True
    except Exception as e:
        print(f"❌ Debug mode test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_is_box_in_roi():
    """Test the _is_box_in_roi method with both modes."""
    from src.services.cleaner_service import SubtitleRemoverService
    import numpy as np
    
    print("=" * 60)
    print("TEST 4: _is_box_in_roi Method")
    print("=" * 60)
    
    class MockInpainter:
        pass
    
    class MockMaskService:
        pass
    
    try:
        # Test percentage mode
        service_pct = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='bottom',  # 60% from bottom
            debug=False
        )
        
        # Create a test bounding box in the center of a 1920x1080 frame
        # Center Y = 540 (middle of screen)
        # ROI limit for bottom 60% = 1080 * (1 - 0.6) = 432
        # So center_y=540 > 432, should be IN ROI
        test_box = [[100, 520], [200, 520], [200, 560], [100, 560]]
        is_in, cx, cy, limit = service_pct._is_box_in_roi(test_box, 1920, 1080)
        
        assert is_in == True, f"Box at y=540 should be in ROI (limit=432)"
        assert abs(cy - 540) < 1, f"Center Y should be 540, got {cy}"
        print(f"✅ Percentage mode (bottom 60%): Box correctly identified as IN ROI")
        print(f"   Center: ({cx:.0f}, {cy:.0f}), ROI limit: {limit:.0f}")
        
        # Test bounding box mode
        service_bbox = SubtitleRemoverService(
            MockMaskService(),
            MockInpainter(),
            lang='en',
            roi_factor='0.05,0.4,0.95,0.6',  # x1=0.05, y1=0.4, x2=0.95, y2=0.6
            debug=False
        )
        
        # Test box in center of screen (should be IN bounding box)
        # Frame: 1920x1080, BBox: x[96-1824], y[432-648]
        # Box center at (960, 540) should be inside
        test_box2 = [[950, 535], [970, 535], [970, 545], [950, 545]]
        is_in2, cx2, cy2, limit2 = service_bbox._is_box_in_roi(test_box2, 1920, 1080)
        
        assert is_in2 == True, f"Box at (960, 540) should be in bounding box"
        print(f"✅ Bounding box mode: Box correctly identified as IN ROI")
        print(f"   Center: ({cx2:.0f}, {cy2:.0f}), BBox: {service_bbox.roi_bbox}")
        
        # Test box outside bounding box (top of screen, y=100)
        test_box3 = [[950, 95], [970, 95], [970, 105], [950, 105]]
        is_in3, cx3, cy3, limit3 = service_bbox._is_box_in_roi(test_box3, 1920, 1080)
        
        assert is_in3 == False, f"Box at (960, 100) should be outside bounding box (y1=432)"
        print(f"✅ Bounding box mode: Box correctly identified as OUTSIDE ROI")
        print(f"   Center: ({cx3:.0f}, {cy3:.0f})")
        
        print("\n✅ All _is_box_in_roi tests PASSED!\n")
        return True
    except Exception as e:
        print(f"❌ _is_box_in_roi test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "="*60)
    print("ROI Improvements Test Suite")
    print("="*60 + "\n")
    
    results = []
    results.append(("ROI Parsing", test_roi_parsing()))
    results.append(("VRAM Detection", test_vram_detection()))
    results.append(("Debug Mode", test_debug_mode()))
    results.append(("is_box_in_roi Method", test_is_box_in_roi()))
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name:30} {status}")
    
    all_passed = all(passed for _, passed in results)
    
    if all_passed:
        print("\n🎉 All tests PASSED! Implementation is working correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests FAILED. Please review the errors above.")
        sys.exit(1)

