#!/usr/bin/env python3
"""
Quick test to verify the restored process method works.
"""
import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.services.streaming_cleaner_service import StreamingSubtitleRemoverService
from src.domain.models import InpaintingRequest

def test_process_method_exists():
    """Check that process method exists and is callable."""
    service = StreamingSubtitleRemoverService(use_gpu=False)
    assert hasattr(service, 'process'), "process method missing"
    assert callable(service.process), "process is not callable"
    print("✓ process method exists and is callable")

def test_process_method_signature():
    """Check that process method accepts InpaintingRequest."""
    import inspect
    service = StreamingSubtitleRemoverService(use_gpu=False)
    sig = inspect.signature(service.process)
    params = list(sig.parameters.keys())
    assert len(params) == 2, f"Expected 2 parameters (self, request), got {params}"
    assert params[0] == 'self'
    assert params[1] == 'request'
    print("✓ process method signature matches InpaintingRequest")

def test_process_with_mock_directories():
    """Test process with empty directories (should fail gracefully)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        # Create a dummy image to avoid empty directory
        from PIL import Image
        dummy_img = Image.new('RGB', (100, 100), color='red')
        dummy_img.save(input_dir / "frame1.png")
        
        request = InpaintingRequest(input_dir=input_dir, output_dir=output_dir)
        service = StreamingSubtitleRemoverService(use_gpu=False)
        # The process will fail because model cannot be loaded (no ProPainter),
        # but we can catch the exception and verify it's not about missing method.
        try:
            result = service.process(request)
            print(f"Process returned: {result.success}")
        except Exception as e:
            # Expected: ModelLoadingError or similar
            print(f"Process raised expected exception: {type(e).__name__}: {e}")
            # Ensure it's not AttributeError about missing 'process'
            assert "process" not in str(e).lower(), f"Unexpected error about missing process: {e}"
    print("✓ process method executed without AttributeError")

if __name__ == "__main__":
    test_process_method_exists()
    test_process_method_signature()
    test_process_with_mock_directories()
    print("\nAll tests passed!")
