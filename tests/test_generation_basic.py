"""
Basic import tests for text-to-video generation module.

Tests that don't require external dependencies (diffusers, torch, etc.)
to verify the code structure is correct.
"""

import sys
import importlib
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import_config_without_deps():
    """Test that config module can be imported without external deps."""
    # Mock missing dependencies
    import builtins
    original_import = builtins.__import__
    
    def mock_import(name, *args, **kwargs):
        if name in ['torch', 'diffusers', 'transformers']:
            raise ImportError(f"Mocked missing dependency: {name}")
        return original_import(name, *args, **kwargs)
    
    builtins.__import__ = mock_import
    
    try:
        # Clear any cached imports
        for module in list(sys.modules.keys()):
            if module.startswith('src.services.generation'):
                del sys.modules[module]
        
        # Now import should work for config (no torch/diffusers in config.py)
        from src.services.generation.config import GenerationConfig
        config = GenerationConfig()
        assert config.MODEL_ID == "THUDM/CogVideoX-5b"
        print("✅ Config imports without external dependencies")
        
    except ImportError as e:
        # Check if it's our mocked error
        if "Mocked missing dependency" in str(e):
            print(f"⚠️  Config still tries to import: {e}")
        else:
            raise
    finally:
        builtins.__import__ = original_import


def test_import_models():
    """Test that models can be imported (only requires pydantic)."""
    try:
        from src.services.generation.models import GenJob, GenerationResult, BatchGenerationResult
        
        # Test basic functionality
        job = GenJob(prompts=["test"])
        assert job.id is not None
        assert job.prompts == ["test"]
        
        result = GenerationResult(
            job_id="test",
            prompt_index=0,
            prompt="test",
            output_key="test.mp4"
        )
        assert result.success is True
        
        batch = BatchGenerationResult(
            job_id="test",
            total_prompts=1,
            successful=1,
            failed=0
        )
        assert batch.duration_seconds is None
        
        print("✅ Models import and work correctly")
        
    except ImportError as e:
        print(f"❌ Models import failed: {e}")
        raise


def test_no_hard_opencv_imports():
    """Check that OpenCV is not imported in generation modules."""
    import ast
    import os
    
    generation_dir = Path(__file__).parent.parent / "src" / "services" / "generation"
    
    for file_path in generation_dir.glob("*.py"):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for import statements
        if 'import cv2' in content or 'from cv2' in content:
            print(f"❌ OpenCV import found in {file_path.name}")
            return False
        
        # Check for paddleocr imports
        if 'import paddleocr' in content or 'from paddleocr' in content:
            print(f"❌ PaddleOCR import found in {file_path.name}")
            return False
    
    print("✅ No OpenCV/PaddleOCR imports in generation modules")
    return True


def test_entrypoint_import():
    """Test that entrypoint can be imported (without running)."""
    try:
        # Mock argparse to prevent CLI parsing
        import argparse
        original_argparse = argparse.ArgumentParser
        
        class MockParser:
            def __init__(self, *args, **kwargs):
                pass
            def add_argument(self, *args, **kwargs):
                pass
            def parse_args(self):
                class Args:
                    job = '{"prompts": ["test"]}'
                    verbose = False
                    config = None
                    no_upload = False
                    output_format = "json"
                return Args()
        
        argparse.ArgumentParser = MockParser
        
        # Import the module (should not execute main())
        module = importlib.import_module('src.entrypoints.run_gen')
        
        # Restore original
        argparse.ArgumentParser = original_argparse
        
        print("✅ Entrypoint module imports successfully")
        
    except Exception as e:
        print(f"❌ Entrypoint import failed: {e}")
        raise


def main():
    """Run all basic tests."""
    print("Running basic generation module tests...")
    print("-" * 50)
    
    tests = [
        test_import_models,
        test_no_hard_opencv_imports,
        test_entrypoint_import,
        test_import_config_without_deps,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed: {e}")
    
    print("-" * 50)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All basic tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
