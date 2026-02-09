#!/usr/bin/env python3
"""
Интеграционный тест для проверки Universal Video Generation Pipeline.
Проверяет базовую функциональность без реальных моделей (моки).
"""

import sys
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_models_updated():
    """Test that GenerationMode enum has been updated correctly."""
    print("🧪 Testing GenerationMode enum updates...")
    
    try:
        from src.services.generation.models import GenerationMode
        
        # Check that only universal and image2video exist (lowercase as defined)
        expected_modes = {"universal", "image2video"}
        actual_modes = {mode.value for mode in GenerationMode}
        
        if actual_modes == expected_modes:
            print("✅ GenerationMode enum updated correctly")
            print(f"   Modes: {list(actual_modes)}")
            return True
        else:
            print(f"❌ GenerationMode mismatch")
            print(f"   Expected: {expected_modes}")
            print(f"   Actual: {actual_modes}")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_genjob_validation():
    """Test that GenJob validation works with new modes."""
    print("\n🧪 Testing GenJob validation...")
    
    try:
        from src.services.generation.models import GenJob, GenerationMode
        
        # Test UNIVERSAL mode (should not allow input_images)
        print("  Testing UNIVERSAL mode...")
        job_universal = GenJob(
            mode=GenerationMode.UNIVERSAL,
            prompts=["Test prompt"],
            input_images=None  # Should be allowed
        )
        print("  ✅ UNIVERSAL mode accepts no input_images")
        
        # Test that UNIVERSAL rejects input_images
        try:
            job_invalid = GenJob(
                mode=GenerationMode.UNIVERSAL,
                prompts=["Test prompt"],
                input_images=["https://example.com/image.jpg"]
            )
            print("  ❌ UNIVERSAL should reject input_images")
            return False
        except ValueError as e:
            if "input_images not allowed for universal mode" in str(e):
                print("  ✅ UNIVERSAL correctly rejects input_images")
            else:
                print(f"  ❌ Wrong error: {e}")
                return False
        
        # Test IMAGE2VIDEO mode (requires input_images)
        print("  Testing IMAGE2VIDEO mode...")
        try:
            job_i2v = GenJob(
                mode=GenerationMode.IMAGE2VIDEO,
                prompts=["Test prompt"],
                input_images=["https://example.com/image.jpg"]
            )
            print("  ✅ IMAGE2VIDEO accepts input_images")
        except ValueError as e:
            print(f"  ❌ IMAGE2VIDEO should accept input_images: {e}")
            return False
        
        # Test IMAGE2VIDEO requires input_images
        try:
            job_i2v_invalid = GenJob(
                mode=GenerationMode.IMAGE2VIDEO,
                prompts=["Test prompt"],
                input_images=None
            )
            print("  ❌ IMAGE2VIDEO should require input_images")
            return False
        except ValueError as e:
            if "input_images required for image2video mode" in str(e):
                print("  ✅ IMAGE2VIDEO correctly requires input_images")
            else:
                print(f"  ❌ Wrong error: {e}")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_orchestrator_integration():
    """Test that orchestrator can handle new modes."""
    print("\n🧪 Testing orchestrator integration...")
    
    try:
        from src.services.generation.models import GenJob, GenerationMode
        from src.services.generation.orchestrator import GenerationOrchestrator
        from src.services.generation.config import GenerationConfig
        
        # Mock B2Client to avoid real connections
        with patch('src.services.generation.orchestrator.B2Client') as mock_b2:
            mock_b2_instance = Mock()
            mock_b2.return_value = mock_b2_instance
            
            # Create orchestrator
            config = GenerationConfig()
            orchestrator = GenerationOrchestrator(config=config)
            
            # Test _get_engine for UNIVERSAL mode
            print("  Testing UNIVERSAL engine creation...")
            # Mock the import inside _get_engine (from .engine import UniversalVideoEngine)
            with patch('src.services.generation.engine.UniversalVideoEngine') as mock_engine:
                mock_engine_instance = Mock()
                mock_engine.return_value = mock_engine_instance
                
                engine = orchestrator._get_engine(GenerationMode.UNIVERSAL)
                assert engine == mock_engine_instance
                print("  ✅ UNIVERSAL engine created successfully")
            
            # Test _get_engine for IMAGE2VIDEO mode
            print("  Testing IMAGE2VIDEO engine creation...")
            # Mock the import inside _get_engine (from .engines.image2video import CogVideoImage2VideoEngine)
            with patch('src.services.generation.engines.image2video.CogVideoImage2VideoEngine') as mock_engine:
                mock_engine_instance = Mock()
                mock_engine.return_value = mock_engine_instance
                
                engine = orchestrator._get_engine(GenerationMode.IMAGE2VIDEO)
                assert engine == mock_engine_instance
                print("  ✅ IMAGE2VIDEO engine created successfully")
            
            # Test invalid mode
            print("  Testing invalid mode handling...")
            try:
                orchestrator._get_engine("invalid_mode")
                print("  ❌ Should raise ValueError for invalid mode")
                return False
            except ValueError as e:
                if "Unknown generation mode" in str(e):
                    print("  ✅ Invalid mode correctly rejected")
                else:
                    print(f"  ❌ Wrong error: {e}")
                    return False
            
            return True
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cli_arguments():
    """Test that CLI arguments are properly parsed."""
    print("\n🧪 Testing CLI argument parsing...")
    
    try:
        from src.entrypoints.run_gen import parse_arguments
        
        # Test with minimal arguments
        test_args = ["--job", '{"prompts": ["test"]}']
        
        with patch('sys.argv', ['run_gen.py'] + test_args):
            args = parse_arguments()
            
            assert args.job == '{"prompts": ["test"]}'
            assert args.verbose == False
            assert args.no_upload == False
            assert args.output_format == "json"
            
            print("  ✅ Basic arguments parsed correctly")
        
        # Test with B2 arguments
        test_args_b2 = [
            "--job", '{"prompts": ["test"]}',
            "--bucket", "test-bucket",
            "--b2-endpoint", "https://test.endpoint.com",
            "--b2-key", "test-key",
            "--b2-secret", "test-secret",
            "--b2-region", "test-region",
            "--verbose",
            "--no-upload"
        ]
        
        with patch('sys.argv', ['run_gen.py'] + test_args_b2):
            args = parse_arguments()
            
            assert args.bucket == "test-bucket"
            assert args.b2_endpoint == "https://test.endpoint.com"
            assert args.b2_key == "test-key"
            assert args.b2_secret == "test-secret"
            assert args.b2_region == "test-region"
            assert args.verbose == True
            assert args.no_upload == True
            
            print("  ✅ B2 arguments parsed correctly")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("🚀 Universal Video Generation Integration Test Suite")
    print("=" * 60)
    
    results = []
    
    # Run tests
    results.append(("GenerationMode Enum", test_models_updated()))
    results.append(("GenJob Validation", test_genjob_validation()))
    results.append(("Orchestrator Integration", test_orchestrator_integration()))
    results.append(("CLI Arguments", test_cli_arguments()))
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results:")
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {test_name:25} {status}")
        if success:
            passed += 1
    
    print(f"\n🎯 {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n✨ All integration tests passed!")
        print("\n📋 Implementation Summary:")
        print("  - GenerationMode enum updated: UNIVERSAL, IMAGE2VIDEO")
        print("  - GenJob validation for both modes implemented")
        print("  - GenerationOrchestrator supports both engines")
        print("  - CLI arguments for B2/S3 added (like pipeline_v2.py)")
        print("  - UniversalVideoEngine ready for two-stage generation")
        print("\n✅ Ready for deployment with Docker image containing:")
        print("   - Lykon/dreamshaper-xl-lightning (T2I)")
        print("   - THUDM/CogVideoX-5b-I2V (I2V)")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())