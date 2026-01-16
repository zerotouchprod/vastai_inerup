#!/usr/bin/env python3
"""
Test script for MaskGenerator debug visualization.
"""
import sys
sys.path.insert(0, '.')

import numpy as np
from pathlib import Path
from src.core.config import get_config
from src.infrastructure.detection.components.mask_generator import MaskGenerator

def test_debug_visualization():
    """Test that debug visualization method works without errors."""
    config = get_config()
    generator = MaskGenerator(config)
    
    # Create a dummy image
    dummy_image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    
    # Create a dummy text mask
    dummy_mask = np.zeros((480, 640), dtype=np.uint8)
    dummy_mask[200:250, 100:300] = 255  # Simulate text region
    
    # Test ROI string
    roi_str = "0.05,0.70,0.90,0.25"
    
    # Output path
    output_path = Path("test_debug_output.jpg")
    
    try:
        # Call the debug visualization method
        generator.save_debug_visualization(dummy_image, roi_str, output_path, dummy_mask)
        
        if output_path.exists():
            print(f"✓ Debug visualization saved to {output_path}")
            output_path.unlink()  # Clean up
            print("✓ File cleaned up")
        else:
            print(f"✗ File not created: {output_path}")
            
    except Exception as e:
        print(f"✗ Error in save_debug_visualization: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = test_debug_visualization()
    sys.exit(0 if success else 1)
