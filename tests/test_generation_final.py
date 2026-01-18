"""
Final validation test for text-to-video generation module.

Tests the most important aspects without requiring external dependencies.
"""

import sys
import ast
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_architecture_isolation():
    """
    Test that generation modules are isolated from OpenCV/PaddleOCR.
    
    This is CRITICAL for the isolated Docker image to work correctly.
    """
    print("Checking architecture isolation...")
    
    # Check generation modules
    generation_dir = Path(__file__).parent.parent / "src" / "services" / "generation"
    forbidden_imports = ['cv2', 'paddleocr', 'opencv', 'PaddleOCR']
    
    issues = []
    
    for file_path in generation_dir.glob("*.py"):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for forbidden imports
        for forbidden in forbidden_imports:
            if f'import {forbidden}' in content or f'from {forbidden}' in content:
                issues.append(f"{file_path.name}: imports {forbidden}")
    
    if issues:
        print("❌ Architecture isolation FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ Architecture isolation passed: No OpenCV/PaddleOCR imports")
        return True


def test_config_defaults():
    """Test that configuration has correct defaults."""
    print("\nChecking configuration defaults...")
    
    from src.services.generation.config import GenerationConfig
    
    config = GenerationConfig()
    
    expected_defaults = {
        'MODEL_ID': 'THUDM/CogVideoX-5b',
        'ENABLE_SAFETY_CHECKER': True,
        'DEFAULT_GUIDANCE_SCALE': 6.0,
        'DEFAULT_NUM_INFERENCE_STEPS': 50,
        'DEFAULT_NUM_FRAMES': 49,
        'DEFAULT_FPS': 8,
    }
    
    issues = []
    for key, expected in expected_defaults.items():
        actual = getattr(config, key)
        if actual != expected:
            issues.append(f"{key}: expected {expected}, got {actual}")
    
    if issues:
        print("❌ Configuration defaults FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ Configuration defaults passed")
        return True


def test_models_functionality():
    """Test that data models work correctly."""
    print("\nTesting data models...")
    
    from src.services.generation.models import GenJob, GenerationResult
    
    # Test GenJob
    job = GenJob(prompts=["A test prompt", "Another prompt"])
    assert job.id is not None
    assert len(job.prompts) == 2
    assert job.guidance_scale == 6.0
    
    # Test JSON serialization
    json_str = job.to_json()
    job_from_json = GenJob.from_json(json_str)
    assert job_from_json.id == job.id
    
    # Test output key generation
    key = job.get_output_key(0)
    assert key.startswith(job.output_prefix)
    assert key.endswith('.mp4')
    
    # Test GenerationResult
    result = GenerationResult(
        job_id="test_job",
        prompt_index=0,
        prompt="test",
        output_key="test.mp4"
    )
    assert result.success is True
    
    print("✅ Data models functionality passed")
    return True


def test_entrypoint_structure():
    """Test that entrypoint has correct structure."""
    print("\nChecking entrypoint structure...")
    
    entrypoint_path = Path(__file__).parent.parent / "src" / "entrypoints" / "run_gen.py"
    
    with open(entrypoint_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for required components
    required_components = [
        'argparse.ArgumentParser',
        'GenJob.from_json',
        'GenerationOrchestrator',
        'json.dumps',
        'setup_logger',
    ]
    
    issues = []
    for component in required_components:
        if component not in content:
            issues.append(f"Missing component: {component}")
    
    # Check shebang
    if not content.startswith('#!/usr/bin/env python3'):
        issues.append("Missing shebang #!/usr/bin/env python3")
    
    # Check main guard
    if 'if __name__ == "__main__":' not in content:
        issues.append("Missing if __name__ == '__main__' guard")
    
    if issues:
        print("❌ Entrypoint structure FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ Entrypoint structure passed")
        return True


def test_dockerfile_structure():
    """Test that Dockerfile has correct structure."""
    print("\nChecking Dockerfile structure...")
    
    dockerfile_path = Path(__file__).parent.parent / "Dockerfile.gen"
    
    with open(dockerfile_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for required patterns (more flexible)
    required_patterns = [
        ('Base image', 'FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime'),
        ('Requirements copy', 'COPY requirements.gen.txt'),
        ('Source code copy', 'COPY src/'),
        ('HF_HOME setting', 'HF_HOME'),
        ('Entrypoint command', 'CMD ["python", "-m", "src.entrypoints.run_gen"'),
    ]
    
    issues = []
    for description, pattern in required_patterns:
        if pattern not in content:
            issues.append(f"Missing {description}: {pattern}")
    
    # Additional check: verify HF_HOME points to correct directory
    if 'HF_HOME' in content:
        # Extract the value
        import re
        hf_home_match = re.search(r'HF_HOME\s*=\s*["\']([^"\']+)["\']', content)
        if hf_home_match:
            hf_home_value = hf_home_match.group(1)
            if '/root/.cache/huggingface' not in hf_home_value:
                issues.append(f"HF_HOME incorrect: {hf_home_value}")
        else:
            issues.append("HF_HOME not properly set (no value found)")
    
    if issues:
        print("❌ Dockerfile structure FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("✅ Dockerfile structure passed")
        return True


def main():
    """Run all validation tests."""
    print("=" * 60)
    print("FINAL VALIDATION: Text-to-Video Generation Module")
    print("=" * 60)
    
    tests = [
        test_architecture_isolation,
        test_config_defaults,
        test_models_functionality,
        test_entrypoint_structure,
        test_dockerfile_structure,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ {test.__name__} failed with exception: {e}")
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{total} tests passed")
    print("=" * 60)
    
    if passed == total:
        print("✅ ALL VALIDATION TESTS PASSED!")
        print("\nThe text-to-video generation module is ready for use.")
        print("Key features verified:")
        print("  - Isolated from OpenCV/PaddleOCR dependencies")
        print("  - Correct configuration defaults")
        print("  - Functional data models")
        print("  - Proper entrypoint structure")
        print("  - Complete Dockerfile")
        return 0
    else:
        print("❌ VALIDATION FAILED")
        print(f"   {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
