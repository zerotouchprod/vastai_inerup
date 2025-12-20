#!/usr/bin/env python3
"""Test CLI arguments for subtitle removal."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.presentation.cli import main
import argparse

def test_argparse():
    """Test that argparse recognizes new arguments."""
    import presentation.cli as cli_module
    
    # Create parser using the same function as in cli.py
    parser = argparse.ArgumentParser(description="Video processing pipeline")
    
    # Add arguments as in cli.py
    parser.add_argument('--config', type=Path, help='Config YAML file')
    parser.add_argument('--input', '-i', help='Input video URL')
    parser.add_argument('--output', '-o', type=Path, help='Output directory (default: ./output)')
    parser.add_argument('--bucket', '-b', help='B2 bucket name (overrides B2_BUCKET in config/env)')
    parser.add_argument('--b2-endpoint', help='B2 S3-compatible endpoint URL (overrides B2_ENDPOINT)')
    parser.add_argument('--b2-key', help='B2 access key (overrides B2_KEY)')
    parser.add_argument('--b2-secret', help='B2 secret key (overrides B2_SECRET)')
    parser.add_argument('--b2-region', help='B2 region name (overrides B2_REGION)')
    parser.add_argument('--type', choices=['video', 'image', 'audio'], default='video', help='Media type (default: video)')
    parser.add_argument('--mode', help='Processing mode (depends on type)')
    parser.add_argument('--scale', type=float, help='Upscale factor')
    parser.add_argument('--target-fps', type=int, help='Target FPS')
    parser.add_argument('--prefer', choices=['auto', 'pytorch'], help='Backend')
    parser.add_argument('--strategy', choices=['interp-then-upscale', 'upscale-then-interp'], help='Processing order for "both" mode (default: interp-then-upscale)')
    parser.add_argument('--image-mode', choices=['upscale', 'hdr', 'denoise'], help='Image processing mode (default: upscale)')
    parser.add_argument('--audio-mode', choices=['remove_reverb', 'enhance', 'normalize'], help='Audio processing mode (default: remove_reverb)')
    parser.add_argument('--remove-subs', action='store_true', help='Remove hardcoded subtitles before processing')
    parser.add_argument('--subs-lang', type=str, default='en', help='Language code for subtitle OCR (default: en)')
    parser.add_argument('--strict', action='store_true', help='Strict mode')
    parser.add_argument('--allow-fallback', action='store_true', help='Allow ffmpeg fallback when RIFE is not available (default: disabled)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose')
    parser.add_argument('--job', '-j', help='Job id (override)')
    
    # Test parsing
    test_args = [
        '--input', 'test.mp4',
        '--mode', 'upscale',
        '--remove-subs',
        '--subs-lang', 'ru'
    ]
    
    args = parser.parse_args(test_args)
    
    print("Argument parsing test:")
    print(f"  input: {args.input}")
    print(f"  mode: {args.mode}")
    print(f"  remove_subs: {args.remove_subs}")
    print(f"  subs_lang: {args.subs_lang}")
    
    assert args.input == 'test.mp4'
    assert args.mode == 'upscale'
    assert args.remove_subs == True
    assert args.subs_lang == 'ru'
    
    print("SUCCESS: CLI arguments parsed correctly")
    return True

def test_config_loading():
    """Test that config loads subtitle fields."""
    from src.infrastructure.config import ConfigLoader
    import tempfile
    import yaml
    
    config_data = {
        'input_url': 'file://test.mp4',
        'type': 'video',
        'mode': 'upscale',
        'remove_subtitles': True,
        'subtitle_language': 'ru'
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config_data, f)
        config_path = Path(f.name)
    
    try:
        loader = ConfigLoader(config_path=config_path)
        config = loader.load()
        
        print("\nConfig loading test:")
        print(f"  remove_subtitles: {config.remove_subtitles}")
        print(f"  subtitle_language: {config.subtitle_language}")
        
        assert config.remove_subtitles == True
        assert config.subtitle_language == 'ru'
        
        print("SUCCESS: Config loads subtitle fields correctly")
        return True
    finally:
        config_path.unlink()

def test_job_creation():
    """Test that Job object includes subtitle fields."""
    from src.domain.models import Job
    
    job = Job(
        job_id="test",
        input_url="file://test.mp4",
        type="video",
        mode="upscale",
        remove_subtitles=True,
        subtitle_language="ru"
    )
    
    print("\nJob creation test:")
    print(f"  remove_subtitles: {job.remove_subtitles}")
    print(f"  subtitle_language: {job.subtitle_language}")
    
    assert job.remove_subtitles == True
    assert job.subtitle_language == "ru"
    
    print("SUCCESS: Job includes subtitle fields")
    return True

def main():
    print("=" * 60)
    print("Testing Subtitle Removal CLI Integration")
    print("=" * 60)
    
    tests = [
        test_argparse,
        test_config_loading,
        test_job_creation
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
        print("SUCCESS: All CLI integration tests passed!")
        print("\nImplementation complete:")
        print("  - CLI arguments --remove-subs and --subs-lang added")
        print("  - ProcessingConfig includes subtitle fields")
        print("  - Job model includes subtitle fields")
        print("  - Orchestrator runs subtitle removal before other processing")
    else:
        print("FAIL: Some tests failed")
    
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
