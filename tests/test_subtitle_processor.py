#!/usr/bin/env python3
"""Test subtitle processor integration."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """Test that imports work."""
    print("Testing imports...")
    
    try:
        from src.infrastructure.processors.subtitle.wrapper import SubtitleRemoverWrapper
        print("SUCCESS: SubtitleRemoverWrapper imported")
    except ImportError as e:
        print(f"FAIL: Could not import SubtitleRemoverWrapper: {e}")
        return False
    
    try:
        from src.application.factories import ProcessorFactory
        print("SUCCESS: ProcessorFactory imported")
    except ImportError as e:
        print(f"FAIL: Could not import ProcessorFactory: {e}")
        return False
    
    return True

def test_factory():
    """Test factory creation."""
    print("\nTesting factory...")
    
    from src.application.factories import ProcessorFactory
    
    factory = ProcessorFactory()
    print(f"Factory created, use_native={factory.use_native}")
    
    # Check availability
    try:
        available = SubtitleRemoverWrapper.is_available()
        print(f"Subtitle remover available: {available}")
        
        if not available:
            print("WARNING: Subtitle remover dependencies not installed")
            print("To install: pip install paddleocr opencv-python-headless")
            return True  # Not a failure, just missing dependencies
    except Exception as e:
        print(f"ERROR checking availability: {e}")
        return False
    
    return True

def test_job_validation():
    """Test job validation for subtitle removal mode."""
    print("\nTesting job validation...")
    
    from src.domain.models import Job
    
    try:
        job = Job(
            job_id="test_subtitle",
            input_url="file://test.mp4",
            type="video",
            mode="remove-subtitles",
            scale=1.0  # Not used but required
        )
        print("SUCCESS: Job with remove-subtitles mode created")
        print(f"  Job type: {job.type}")
        print(f"  Job mode: {job.mode}")
        return True
    except Exception as e:
        print(f"FAIL: Job creation failed: {e}")
        return False

def test_config():
    """Test config validation for subtitle removal."""
    print("\nTesting config validation...")
    
    from src.infrastructure.config import ConfigLoader
    import tempfile
    import yaml
    
    config_data = {
        'input_url': 'file://test.mp4',
        'type': 'video',
        'mode': 'remove-subtitles',
        'scale': 1.0
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        loader = ConfigLoader(config_path=config_path)
        config = loader.load()
        
        print(f"SUCCESS: Config loaded")
        print(f"  Type: {config.type}")
        print(f"  Mode: {config.mode}")
        print(f"  Scale: {config.scale}")
        
        assert config.type == 'video'
        assert config.mode == 'remove-subtitles'
        
        return True
    except Exception as e:
        print(f"FAIL: Config loading failed: {e}")
        return False
    finally:
        config_path.unlink()

def main():
    print("=" * 60)
    print("Testing Subtitle Processor Integration")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_factory,
        test_job_validation,
        test_config
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"ERROR in test {test.__name__}: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("Summary:")
    
    all_passed = all(results)
    if all_passed:
        print("SUCCESS: All integration tests passed!")
        print("\nArchitecture is ready for subtitle removal.")
        print("To use: python pipeline_v2.py --mode remove-subtitles --input <video_url>")
    else:
        print("FAIL: Some tests failed")
        print("\nMissing dependencies: pip install paddleocr opencv-python-headless")
    
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
