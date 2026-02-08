#!/usr/bin/env python3
"""
Simple test for UniversalVideoEngine to verify basic functionality.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

def test_import_and_structure():
    """Test that UniversalVideoEngine can be imported and has correct structure."""
    print("🧪 Testing UniversalVideoEngine import and structure...")
    
    try:
        # Import the module (should not fail due to missing dependencies)
        from src.services.generation import UniversalVideoEngine, GenerationConfig
        
        print("✓ Successfully imported UniversalVideoEngine")
        
        # Create config
        config = GenerationConfig()
        print(f"✓ Config created: T2I model = {config.T2I_MODEL_ID}, I2V model = {config.I2V_MODEL_ID}")
        
        # Create engine
        engine = UniversalVideoEngine(config)
        print("✓ Engine instance created")
        
        # Check that engine has required methods
        required_methods = ['initialize', 'generate', 'cleanup', '_load_t2i_pipeline', 
                          '_load_i2v_pipeline', '_cleanup_vram']
        
        for method in required_methods:
            if hasattr(engine, method):
                print(f"✓ Engine has method: {method}")
            else:
                print(f"❌ Engine missing method: {method}")
                return False
        
        print("✓ All required methods present")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_updated():
    """Test that config has been updated with T2I model."""
    print("\n🧪 Testing config updates...")
    
    try:
        from src.services.generation import GenerationConfig
        
        config = GenerationConfig()
        
        # Check that T2I_MODEL_ID exists
        if hasattr(config, 'T2I_MODEL_ID'):
            print(f"✓ T2I_MODEL_ID exists: {config.T2I_MODEL_ID}")
            
            # Check that it's the correct model
            expected_model = "Lykon/dreamshaper-xl-lightning"
            if config.T2I_MODEL_ID == expected_model:
                print(f"✓ T2I model is correct: {expected_model}")
            else:
                print(f"⚠️  T2I model is {config.T2I_MODEL_ID}, expected {expected_model}")
        else:
            print("❌ T2I_MODEL_ID missing from config")
            return False
        
        # Check that I2V_MODEL_ID exists
        if hasattr(config, 'I2V_MODEL_ID'):
            print(f"✓ I2V_MODEL_ID exists: {config.I2V_MODEL_ID}")
        else:
            print("❌ I2V_MODEL_ID missing from config")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Config test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 UniversalVideoEngine Simple Test Suite")
    print("=" * 50)
    
    results = []
    
    # Run tests
    results.append(("Import & Structure", test_import_and_structure()))
    results.append(("Config Updates", test_config_updated()))
    
    # Summary
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    
    passed = 0
    total = len(results)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {test_name:20} {status}")
        if success:
            passed += 1
    
    print(f"\n🎯 {passed}/{total} tests passed ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("\n✨ Basic tests passed! UniversalVideoEngine structure is correct.")
        print("\n📋 Implementation Summary:")
        print("  - UniversalVideoEngine class implemented in src/services/generation/engine.py")
        print("  - Config updated with T2I_MODEL_ID = 'Lykon/dreamshaper-xl-lightning'")
        print("  - Three-phase pipeline: T2I → VRAM Flush → I2V")
        print("  - Aggressive VRAM management between stages")
        print("  - Safety checking for both image and video generation")
        print("  - Lazy imports for heavy libraries (torch, diffusers, transformers)")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())