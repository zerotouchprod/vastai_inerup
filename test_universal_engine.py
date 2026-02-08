#!/usr/bin/env python3
"""
Test script for UniversalVideoEngine.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

# Mock diffusers and transformers before importing
import unittest.mock as mock

# Create mock modules
mock_diffusers = mock.MagicMock()
mock_diffusers.CogVideoXPipeline = mock.MagicMock()
mock_diffusers.CogVideoXImageToVideoPipeline = mock.MagicMock()
mock_diffusers.StableDiffusionXLPipeline = mock.MagicMock()
mock_diffusers.EulerDiscreteScheduler = mock.MagicMock()
mock_diffusers.utils = mock.MagicMock()
mock_diffusers.utils.export_to_video = mock.MagicMock()

mock_transformers = mock.MagicMock()
mock_transformers.pipeline = mock.MagicMock()

# Patch sys.modules before importing
sys.modules['diffusers'] = mock_diffusers
sys.modules['transformers'] = mock_transformers

from src.services.generation import UniversalVideoEngine, GenerationConfig


def test_import_and_initialization():
    """Test that UniversalVideoEngine can be imported and initialized."""
    print("🧪 Testing UniversalVideoEngine import and initialization...")
    
    try:
        # Create config
        config = GenerationConfig()
        
        # Create engine
        engine = UniversalVideoEngine(config)
        
        print(f"✓ Engine created successfully")
        print(f"  T2I model: {config.T2I_MODEL_ID}")
        print(f"  I2V model: {config.I2V_MODEL_ID}")
        
        # Test initialization (should only load safety checker)
        engine.initialize()
        print("✓ Engine initialized (safety checker loaded)")
        
        # Test cleanup
        engine.cleanup()
        print("✓ Engine cleaned up")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_context_manager():
    """Test context manager usage."""
    print("\n🧪 Testing context manager...")
    
    try:
        with UniversalVideoEngine() as engine:
            print(f"✓ Context manager entered")
            print(f"  Engine initialized: {engine._initialized}")
        
        print("✓ Context manager exited (cleanup called)")
        return True
        
    except Exception as e:
        print(f"❌ Context manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mocked_generation():
    """Test generation with mocked pipelines."""
    print("\n🧪 Testing mocked generation...")
    
    try:
        import unittest.mock as mock
        
        # Create engine
        engine = UniversalVideoEngine()
        
        # Mock the pipeline loading methods
        with mock.patch.object(engine, '_load_t2i_pipeline') as mock_load_t2i, \
             mock.patch.object(engine, '_load_i2v_pipeline') as mock_load_i2v, \
             mock.patch.object(engine, '_cleanup_vram') as mock_cleanup, \
             mock.patch('PIL.Image.open') as mock_image_open, \
             mock.patch('diffusers.utils.export_to_video') as mock_export:
            
            # Mock image
            mock_image = mock.MagicMock()
            mock_image_open.return_value = mock_image
            
            # Mock T2I pipeline
            mock_t2i_pipe = mock.MagicMock()
            mock_t2i_output = mock.MagicMock()
            mock_t2i_output.images = [mock_image]
            mock_t2i_pipe.return_value = mock_t2i_output
            engine.t2i_pipe = mock_t2i_pipe
            
            # Mock I2V pipeline
            mock_i2v_pipe = mock.MagicMock()
            mock_i2v_output = mock.MagicMock()
            mock_i2v_output.frames = [[mock_image, mock_image, mock_image]]
            mock_i2v_pipe.return_value = mock_i2v_output
            engine.i2v_pipe = mock_i2v_pipe
            
            # Mock safety checker
            engine.safety_checker = mock.MagicMock()
            engine.safety_checker.return_value = [{'label': 'safe', 'score': 0.1}]
            
            # Mock export
            mock_export.return_value = None
            
            # Initialize engine
            engine._initialized = True
            
            # Create temp directory
            import tempfile
            temp_dir = Path(tempfile.mkdtemp())
            engine.config.TEMP_DIR = str(temp_dir)
            
            # Test generation
            try:
                # This should work with mocked pipelines
                result = engine.generate(
                    prompt="Test prompt",
                    t2i_steps=2,  # Minimal for test
                    num_frames=3,  # Minimal for test
                    num_inference_steps=2  # Minimal for test
                )
                print(f"✓ Mocked generation completed")
                print(f"  Result path: {result}")
                return True
                
            except Exception as e:
                print(f"❌ Mocked generation failed: {e}")
                import traceback
                traceback.print_exc()
                return False
                
    except Exception as e:
        print(f"❌ Mock setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("🚀 UniversalVideoEngine Test Suite")
    print("=" * 50)
    
    results = []
    
    # Run tests
    results.append(("Import & Initialization", test_import_and_initialization()))
    results.append(("Context Manager", test_context_manager()))
    results.append(("Mocked Generation", test_mocked_generation()))
    
    # Summary
    print("\n" + "=" * 50)
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
        print("\n✨ All tests passed! UniversalVideoEngine is ready.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check implementation.")
        return 1


if __name__ == "__main__":
    sys.exit(main())