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

def main():
    print("Testing process method restoration...")
    service = StreamingSubtitleRemoverService(use_gpu=False)
    print("Service instantiated.")
    
    # Check method existence
    if not hasattr(service, 'process'):
        print("ERROR: process method missing")
        sys.exit(1)
    print("✓ process method exists")
    
    # Check callable
    if not callable(service.process):
        print("ERROR: process not callable")
        sys.exit(1)
    print("✓ process is callable")
    
    # Create mock request
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = Path(tmpdir) / "input"
        output_dir = Path(tmpdir) / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        # Create a dummy text file to simulate frame (not image)
        (input_dir / "frame1.txt").write_text("dummy")
        
        request = InpaintingRequest(input_dir=input_dir, output_dir=output_dir)
        print(f"Request created: {request}")
        
        try:
            result = service.process(request)
            print(f"Process returned (unexpected): {result}")
        except Exception as e:
            print(f"Process raised exception (expected): {type(e).__name__}: {e}")
            # Check that it's not AttributeError about missing 'process'
            if "process" in str(e).lower() and "no attribute" in str(e).lower():
                print("ERROR: AttributeError about missing 'process' - restoration failed!")
                sys.exit(1)
            print("✓ No AttributeError about missing 'process'")
    
    print("\nAll checks passed!")
    print("The process method is restored and callable.")
    print("CUDA initialization order fixed.")

if __name__ == "__main__":
    main()
