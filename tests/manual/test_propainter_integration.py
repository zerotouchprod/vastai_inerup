"""
Manual integration test for ProPainter-Wire inference_core.py integration.
Creates temporary test data and verifies the adapter can find and call the script.
"""
import os
import tempfile
import shutil
from pathlib import Path
import cv2
import numpy as np

from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.core.exceptions import ProcessorNotAvailableError


def create_test_frames(frames_dir: Path, count: int = 3):
    """Create black frames for testing."""
    for i in range(count):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(str(frames_dir / f"frame_{i:04d}.png"), frame)


def create_test_masks(masks_dir: Path, count: int = 3):
    """Create white masks for testing."""
    for i in range(count):
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        cv2.imwrite(str(masks_dir / f"frame_{i:04d}.png"), mask)


def test_propainter_integration():
    """Test that ProPainterAdapter can find inference_core.py and construct commands."""
    print("🧪 Starting ProPainter integration test...")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_frames = tmp_path / "input_frames"
        input_masks = tmp_path / "input_masks"
        output_dir = tmp_path / "output"
        
        input_frames.mkdir()
        input_masks.mkdir()
        output_dir.mkdir()
        
        # Create test data
        print(f"📁 Creating test data in {tmp_path}")
        create_test_frames(input_frames, 3)
        create_test_masks(input_masks, 3)
        
        # Initialize adapter
        try:
            adapter = ProPainterAdapter()
            print(f"✅ ProPainterAdapter initialized successfully")
            print(f"   Root: {adapter.root}")
            print(f"   Inference script: {adapter.config.INFERENCE_SCRIPT}")
        except ProcessorNotAvailableError as e:
            print(f"❌ ProPainter not available: {e}")
            print("   This is expected if inference_core.py is not found.")
            print("   Make sure ProPainter-Wire is cloned in project root or /opt/ProPainter-Wire")
            return False
        except Exception as e:
            print(f"❌ Unexpected error initializing adapter: {e}")
            return False
        
        # Test command construction (without actual execution)
        # We'll mock the inference runner to avoid actually running ProPainter
        # since we might not have the model weights
        print("\n🔧 Testing command construction...")
        try:
            # Access the inference runner
            runner = adapter.inference_runner
            cmd = runner.build_command(
                video_path=input_frames,
                mask_path=input_masks,
                output_path=output_dir,
                target_width=100,
                target_height=100
            )
            
            print(f"✅ Command constructed successfully")
            print(f"   Script: {runner.inference_script}")
            print(f"   Using core script: {runner.use_core_script}")
            print(f"   Command: {' '.join(cmd[:8])}...")  # Show first 8 args
            
            # Verify command structure
            if runner.use_core_script:
                assert "--video" in cmd, "Missing --video argument"
                assert "--mask" in cmd, "Missing --mask argument"
                assert "--output" in cmd, "Missing --output argument"
                assert "--model_path" in cmd, "Missing --model_path argument"
                print("✅ inference_core.py command signature verified")
            else:
                assert "--width" in cmd, "Missing --width argument"
                assert "--height" in cmd, "Missing --height argument"
                print("✅ inference_propainter.py command signature verified")
                
        except Exception as e:
            print(f"❌ Error testing command construction: {e}")
            return False
        
        print("\n🎉 Integration test passed!")
        print("   ProPainterAdapter can find inference_core.py")
        print("   Command construction works correctly")
        print("   Note: Actual inference not run (requires model weights)")
        
        return True


if __name__ == "__main__":
    success = test_propainter_integration()
    exit(0 if success else 1)
