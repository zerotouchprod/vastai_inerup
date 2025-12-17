#!/usr/bin/env python3
"""Test simplified subtitle removal (mode-only approach)."""

import sys
from pathlib import Path
import tempfile
import yaml

# Mock the imports that fail
class MockCV2:
    pass

class MockPaddleOCR:
    pass

# Add mock modules to sys.modules before importing our code
sys.modules['cv2'] = MockCV2()
sys.modules['paddleocr'] = MockPaddleOCR()

# Now import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_mode_only():
    """Test that only mode-based subtitle removal works."""
    from infrastructure.config import ConfigLoader
    
    # Test 1: remove-subtitles mode with language
    config_data = {
        'input_url': 'file://test.mp4',
        'type': 'video',
        'mode': 'remove-subtitles',
        'subtitle_language': 'ru'
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        loader = ConfigLoader(config_path=config_path)
        config = loader.load()
        
        print("Test 1 - remove-subtitles mode:")
        print(f"  mode: {config.mode} (expected: remove-subtitles)")
        print(f"  subtitle_language: {config.subtitle_language} (expected: 'ru')")
        
        assert config.mode == 'remove-subtitles'
        assert config.subtitle_language == 'ru'
        
        # Check that remove_subtitles field doesn't exist
        assert not hasattr(config, 'remove_subtitles'), "remove_subtitles field should not exist"
        
        print("SUCCESS: Mode-only approach works")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        config_path.unlink()

def test_no_preprocessing():
    """Test that preprocessing subtitle removal is not available."""
    from infrastructure.config import ConfigLoader
    
    # Test 2: upscale mode should NOT have subtitle removal
    config_data = {
        'input_url': 'file://test.mp4',
        'type': 'video',
        'mode': 'upscale',
        # No remove_subtitles field
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        loader = ConfigLoader(config_path=config_path)
        config = loader.load()
        
        print("\nTest 2 - upscale mode (no subtitle removal):")
        print(f"  mode: {config.mode} (expected: upscale)")
        
        assert config.mode == 'upscale'
        # Should not have remove_subtitles field
        assert not hasattr(config, 'remove_subtitles'), "remove_subtitles field should not exist"
        
        print("SUCCESS: No preprocessing subtitle removal")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        config_path.unlink()

def test_job_model():
    """Test that Job model reflects simplified approach."""
    from domain.models import Job
    
    # Test remove-subtitles mode
    job = Job(
        job_id="test",
        input_url="file://test.mp4",
        type="video",
        mode="remove-subtitles",
        subtitle_language="ru"
    )
    
    print("\nTest 3 - Job model:")
    print(f"  mode: {job.mode} (expected: remove-subtitles)")
    print(f"  subtitle_language: {job.subtitle_language} (expected: 'ru')")
    
    assert job.mode == "remove-subtitles"
    assert job.subtitle_language == "ru"
    
    # Should not have remove_subtitles attribute
    assert not hasattr(job, 'remove_subtitles'), "Job should not have remove_subtitles attribute"
    
    print("SUCCESS: Job model simplified correctly")
    return True

def test_cli_arguments():
    """Test that CLI arguments are correct."""
    # Read CLI file to check arguments
    cli_path = Path(__file__).parent / "src" / "presentation" / "cli.py"
    with open(cli_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("\nTest 4 - CLI arguments:")
    
    # Check that --remove-subs flag is NOT present
    if '--remove-subs' in content:
        print("  FAIL: --remove-subs flag still present (should be removed)")
        return False
    else:
        print("  OK: --remove-subs flag removed")
    
    # Check that --subs-lang is present
    if '--subs-lang' in content:
        print("  OK: --subs-lang argument present")
    else:
        print("  WARNING: --subs-lang argument missing")
    
    # Check that mode help mentions remove-subtitles
    if 'remove-subtitles' in content:
        print("  OK: remove-subtitles mode documented")
    else:
        print("  WARNING: remove-subtitles mode not documented")
    
    return True

def main():
    print("=" * 60)
    print("Testing Simplified Subtitle Removal (Mode-Only)")
    print("=" * 60)
    
    tests = [
        test_mode_only,
        test_no_preprocessing,
        test_job_model,
        test_cli_arguments
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"ERROR in test {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print("Summary:")
    
    all_passed = all(results)
    if all_passed:
        print("SUCCESS: All tests passed!")
        print("\nSimplified implementation complete:")
        print("  1. Removed remove_subtitles field from ProcessingConfig")
        print("  2. Removed preprocessing subtitle removal functionality")
        print("  3. Subtitle removal is now ONLY available via --mode remove-subtitles")
        print("  4. Language selection via --subs-lang argument")
        print("\nUsage:")
        print("  python pipeline_v2.py --mode remove-subtitles --input video.mp4 --subs-lang ru")
        print("\nNote: Subtitle removal is no longer available as a preprocessing step.")
        print("      To remove subtitles and then upscale, run two separate commands.")
    else:
        print("FAIL: Some tests failed")
    
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
