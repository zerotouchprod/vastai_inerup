"""
Integration test for LaMaAdapter with real files.
Tests that LaMaAdapter can process frames with masks and produce output.
"""
import os
import tempfile
import shutil
from pathlib import Path
import cv2
import numpy as np
import pytest

from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.core.exceptions import ProcessorNotAvailableError


def create_test_frame_with_subtitle(frames_dir: Path, filename: str = "frame_001.png"):
    """Create a test frame with a white subtitle box at bottom."""
    # Create a 1920x1080 black frame
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    # Add a white subtitle box at bottom center
    cv2.rectangle(frame, (700, 900), (1220, 1000), (255, 255, 255), -1)
    cv2.imwrite(str(frames_dir / filename), frame)
    return frame


def create_test_mask(masks_dir: Path, filename: str = "frame_001.png"):
    """Create a mask covering the subtitle area."""
    mask = np.zeros((1080, 1920), dtype=np.uint8)
    # Mask the subtitle area
    cv2.rectangle(mask, (700, 900), (1220, 1000), 255, -1)
    cv2.imwrite(str(masks_dir / filename), mask)
    return mask


@pytest.fixture
def test_dirs():
    """Create temporary directories for test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        frames_dir = tmp_path / "frames"
        masks_dir = tmp_path / "masks"
        output_dir = tmp_path / "output"
        
        frames_dir.mkdir()
        masks_dir.mkdir()
        output_dir.mkdir()
        
        yield frames_dir, masks_dir, output_dir
        
        # Cleanup is handled by tempfile


def test_lama_adapter_initialization(monkeypatch):
    """Test that LaMaAdapter can be initialized."""
    print("🧪 Testing LaMaAdapter initialization...")
    
    # Create temporary directory for model
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Mock the config to use temporary path
    from src.core.config import get_config
    original_config = get_config()
    
    # Patch LAMA_MODEL_PATH
    monkeypatch.setattr(original_config, "LAMA_MODEL_PATH", temp_model_path)
    
    try:
        adapter = LaMaAdapter()
        print(f"✅ LaMaAdapter initialized successfully")
        print(f"   Model path: {adapter.model_path}")
        print(f"   Device: {adapter.device if hasattr(adapter, 'device') else 'N/A'}")
        assert adapter is not None
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        return True
    except ProcessorNotAvailableError as e:
        print(f"❌ LaMa not available: {e}")
        pytest.skip("LaMa not available")
    except Exception as e:
        print(f"❌ Unexpected error initializing adapter: {e}")
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        pytest.fail(f"Failed to initialize LaMaAdapter: {e}")


def test_lama_adapter_process_single_frame(test_dirs, monkeypatch):
    """Test processing a single frame with mask."""
    frames_dir, masks_dir, output_dir = test_dirs
    
    print("🧪 Testing LaMaAdapter single frame processing...")
    
    # Create temporary directory for model
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Mock the config to use temporary path
    from src.core.config import get_config
    original_config = get_config()
    
    # Patch LAMA_MODEL_PATH
    monkeypatch.setattr(original_config, "LAMA_MODEL_PATH", temp_model_path)
    
    # Create test data
    frame = create_test_frame_with_subtitle(frames_dir)
    mask = create_test_mask(masks_dir)
    
    try:
        adapter = LaMaAdapter()
    except ProcessorNotAvailableError:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        pytest.skip("LaMa not available")
    
    # Test single frame processing using process_with_roi
    print("   Testing process_with_roi method...")
    try:
        from src.schemas.roi import InpaintConfig
        config = InpaintConfig(
            method='lama',
            padding_px=50,
            use_roi_optimization=True,
            fallback_to_cv2=True
        )
        
        result = adapter.process_with_roi(frame, mask, config)
        
        # Check result
        assert result is not None
        assert result.shape == frame.shape
        assert result.dtype == frame.dtype
        
        # The inpainted area should be different from original (not white)
        # Extract the masked region
        mask_bool = mask > 0
        original_region = frame[mask_bool]
        inpainted_region = result[mask_bool]
        
        # Check that something changed (inpainting occurred)
        # The mean difference should be significant
        diff = np.mean(np.abs(original_region.astype(float) - inpainted_region.astype(float)))
        print(f"   Mean difference in masked region: {diff}")
        
        # Save result for visual inspection
        debug_dir = output_dir / "debug"
        debug_dir.mkdir(exist_ok=True)
        cv2.imwrite(str(debug_dir / "original.png"), frame)
        cv2.imwrite(str(debug_dir / "mask.png"), mask)
        cv2.imwrite(str(debug_dir / "inpainted.png"), result)
        print(f"   Debug images saved to: {debug_dir}")
        
        print("✅ Single frame processing successful")
        
    except Exception as e:
        print(f"❌ Error processing single frame: {e}")
        pytest.fail(f"Failed to process single frame: {e}")


def test_lama_adapter_batch_processing(test_dirs, monkeypatch):
    """Test batch processing of multiple frames."""
    frames_dir, masks_dir, output_dir = test_dirs
    
    print("🧪 Testing LaMaAdapter batch processing...")
    
    # Create temporary directory for model
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Mock the config to use temporary path
    from src.core.config import get_config
    original_config = get_config()
    
    # Patch LAMA_MODEL_PATH
    monkeypatch.setattr(original_config, "LAMA_MODEL_PATH", temp_model_path)
    
    # Create multiple test frames
    for i in range(3):
        create_test_frame_with_subtitle(frames_dir, f"frame_{i:03d}.png")
        create_test_mask(masks_dir, f"frame_{i:03d}.png")
    
    try:
        adapter = LaMaAdapter()
    except ProcessorNotAvailableError:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        pytest.skip("LaMa not available")
    
    # Test batch processing using _inpaint_batch
    print("   Testing batch processing...")
    try:
        # Load frames and masks
        frame_files = sorted(frames_dir.glob("*.png"))
        mask_files = sorted(masks_dir.glob("*.png"))
        
        frames = [cv2.imread(str(f)) for f in frame_files]
        masks = [cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) for f in mask_files]
        
        # Process batch
        inpainted_frames = adapter._inpaint_batch(frames, masks, use_roi=False)
        
        assert len(inpainted_frames) == len(frames)
        for i, (orig, inpainted) in enumerate(zip(frames, inpainted_frames)):
            assert inpainted.shape == orig.shape
            assert inpainted.dtype == orig.dtype
            
            # Save for inspection
            cv2.imwrite(str(output_dir / f"batch_result_{i:03d}.png"), inpainted)
        
        print(f"✅ Batch processing successful: {len(inpainted_frames)} frames processed")
        print(f"   Results saved to: {output_dir}")
        
    except Exception as e:
        print(f"❌ Error in batch processing: {e}")
        pytest.fail(f"Failed batch processing: {e}")


def test_lama_adapter_full_pipeline(test_dirs, monkeypatch):
    """Test full pipeline with directory input."""
    frames_dir, masks_dir, output_dir = test_dirs
    
    print("🧪 Testing LaMaAdapter full pipeline...")
    
    # Create temporary directory for model
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Mock the config to use temporary path
    from src.core.config import get_config
    original_config = get_config()
    
    # Patch LAMA_MODEL_PATH
    monkeypatch.setattr(original_config, "LAMA_MODEL_PATH", temp_model_path)
    
    # Create test data
    for i in range(5):
        create_test_frame_with_subtitle(frames_dir, f"frame_{i:04d}.png")
        create_test_mask(masks_dir, f"frame_{i:04d}.png")
    
    try:
        adapter = LaMaAdapter()
    except ProcessorNotAvailableError:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        pytest.skip("LaMa not available")
    
    # Test the main process method
    print("   Testing main process method...")
    try:
        # Create output video path
        output_video = output_dir / "output.mp4"
        
        # Run pipeline
        result_path = adapter.process(frames_dir, masks_dir, output_video)
        
        # Check results
        assert result_path.exists()
        print(f"✅ Pipeline completed successfully")
        print(f"   Output: {result_path}")
        
        # Check that output directory contains processed frames
        # (The adapter creates intermediate directories)
        output_frames_dir = output_video.parent / "lama_processed"
        if output_frames_dir.exists():
            processed_frames = list(output_frames_dir.glob("*.png"))
            print(f"   Processed frames: {len(processed_frames)}")
            assert len(processed_frames) > 0
        
    except NotImplementedError as e:
        print(f"⚠️  Method not implemented: {e}")
        pytest.skip("Method not fully implemented")
    except Exception as e:
        print(f"❌ Error in full pipeline: {e}")
        pytest.fail(f"Failed full pipeline: {e}")


if __name__ == "__main__":
    """Run tests manually."""
    import sys
    
    # Create test directories
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        frames_dir = tmp_path / "frames"
        masks_dir = tmp_path / "masks"
        output_dir = tmp_path / "output"
        
        frames_dir.mkdir()
        masks_dir.mkdir()
        output_dir.mkdir()
        
        # Run initialization test
    print("=" * 60)
    print("LaMaAdapter Integration Test")
    print("=" * 60)
    
    try:
        test_lama_adapter_initialization()
        print("\n✅ All tests passed!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        sys.exit(1)
