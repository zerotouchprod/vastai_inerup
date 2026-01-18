#!/usr/bin/env python3
"""
Demo script for LaMaAdapter integration.
Processes a test frame with a synthetic subtitle mask.
"""
import os
import sys
from pathlib import Path
import cv2
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.core.config import get_config

def create_test_frame(width=1920, height=1080):
    """Create a test frame with a white subtitle box."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # Add some background texture
    cv2.rectangle(frame, (100, 100), (500, 300), (50, 50, 50), -1)
    cv2.rectangle(frame, (600, 400), (900, 600), (100, 100, 100), -1)
    
    # Add white subtitle box at bottom
    cv2.rectangle(frame, (700, 900), (1220, 1000), (255, 255, 255), -1)
    # Add some text-like pattern
    cv2.rectangle(frame, (720, 920), (800, 940), (200, 200, 200), -1)
    cv2.rectangle(frame, (850, 920), (950, 940), (200, 200, 200), -1)
    cv2.rectangle(frame, (1000, 920), (1100, 940), (200, 200, 200), -1)
    
    return frame

def create_test_mask(width=1920, height=1080):
    """Create a mask covering the subtitle area."""
    mask = np.zeros((height, width), dtype=np.uint8)
    # Mask the subtitle area
    cv2.rectangle(mask, (700, 900), (1220, 1000), 255, -1)
    # Dilate slightly to cover edges
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    return mask

def main():
    print("=" * 60)
    print("LaMaAdapter Demo")
    print("=" * 60)
    
    # Create output directory
    output_dir = Path("demo_output")
    output_dir.mkdir(exist_ok=True)
    
    # Create test frame and mask
    print("Creating test frame and mask...")
    frame = create_test_frame()
    mask = create_test_mask()
    
    # Save original
    cv2.imwrite(str(output_dir / "original.png"), frame)
    cv2.imwrite(str(output_dir / "mask.png"), mask)
    print(f"Saved original and mask to {output_dir}")
    
    # Initialize LaMaAdapter with monkeypatch
    print("\nInitializing LaMaAdapter...")
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Use monkeypatch to modify config
    import sys
    if 'pytest' not in sys.modules:
        # Create our own monkeypatch-like functionality
        from unittest.mock import patch
        from src.core.config import get_config
        
        config = get_config()
        original_value = config.LAMA_MODEL_PATH
        
        try:
            # Temporarily patch the config
            config.LAMA_MODEL_PATH = temp_model_path
            adapter = LaMaAdapter()
            print(f"✅ LaMaAdapter initialized")
            print(f"   Model path: {adapter.model_path}")
            print(f"   Device: {adapter.device if hasattr(adapter, 'device') else 'N/A'}")
        except Exception as e:
            print(f"❌ Failed to initialize LaMaAdapter: {e}")
            # Restore original value
            config.LAMA_MODEL_PATH = original_value
            raise
        finally:
            # Cleanup temp dir will happen later
            pass
    else:
        # In pytest environment, use monkeypatch fixture
        # This won't happen in standalone demo
        pass
    
    # Process single frame
    print("\nProcessing frame with LaMa...")
    try:
        from src.schemas.roi import InpaintConfig
        config = InpaintConfig(
            method='lama',
            padding_px=50,
            use_roi_optimization=True,
            fallback_to_cv2=True
        )
        
        result = adapter.process_with_roi(frame, mask, config)
        
        # Save result
        cv2.imwrite(str(output_dir / "inpainted.png"), result)
        print(f"✅ Frame processed successfully")
        print(f"   Result saved to {output_dir / 'inpainted.png'}")
        
        # Calculate metrics
        mask_bool = mask > 0
        original_region = frame[mask_bool]
        inpainted_region = result[mask_bool]
        
        diff = np.mean(np.abs(original_region.astype(float) - inpainted_region.astype(float)))
        print(f"   Mean difference in masked region: {diff:.2f}")
        
        # Visual comparison
        print("\nVisual comparison:")
        print("   Original masked region mean: ", np.mean(original_region))
        print("   Inpainted region mean: ", np.mean(inpainted_region))
        
        if diff > 10:  # Significant change
            print("   ✅ Inpainting successful - significant change detected")
        else:
            print("   ⚠️  Inpainting may not have worked - minimal change detected")
            
    except Exception as e:
        print(f"❌ Error processing frame: {e}")
        import traceback
        traceback.print_exc()
    
    # Test batch processing
    print("\n" + "=" * 60)
    print("Testing batch processing...")
    
    # Create multiple frames
    frames = []
    masks = []
    for i in range(3):
        frame_i = create_test_frame()
        mask_i = create_test_mask()
        frames.append(frame_i)
        masks.append(mask_i)
        cv2.imwrite(str(output_dir / f"batch_frame_{i}.png"), frame_i)
        cv2.imwrite(str(output_dir / f"batch_mask_{i}.png"), mask_i)
    
    try:
        inpainted_frames = adapter._inpaint_batch(frames, masks, use_roi=False)
        
        for i, inpainted in enumerate(inpainted_frames):
            cv2.imwrite(str(output_dir / f"batch_result_{i}.png"), inpainted)
        
        print(f"✅ Batch processing successful")
        print(f"   Results saved to {output_dir}")
        
    except Exception as e:
        print(f"❌ Batch processing failed: {e}")
    
    print("\n" + "=" * 60)
    print("Demo completed!")
    print(f"Check results in: {output_dir.absolute()}")
    print("=" * 60)

if __name__ == "__main__":
    main()
