"""
Test imports for video generation module (Text-to-Video & Image-to-Video).

Verifies that all modules can be imported without errors,
critical for ensuring the isolated runtime works correctly.
"""

import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import_generation_modules():
    """Test that all generation modules can be imported."""
    from src.services.generation.config import GenerationConfig
    from src.services.generation.models import GenJob, GenerationResult, BatchGenerationResult, GenerationMode
    from src.services.generation.engines.base import BaseVideoEngine
    from src.services.generation.engines.text2video import CogVideoText2VideoEngine
    from src.services.generation.orchestrator import GenerationOrchestrator
    
    # Verify classes exist
    assert GenerationConfig is not None
    assert GenJob is not None
    assert GenerationResult is not None
    assert BatchGenerationResult is not None
    assert GenerationMode is not None
    assert BaseVideoEngine is not None
    assert CogVideoText2VideoEngine is not None
    assert GenerationOrchestrator is not None
    
    print("✅ All generation modules import successfully")


def test_import_domain_layer():
    """Test domain layer imports."""
    from src.domain.generation import IVideoGenerator, GenerationMode, VideoGenerationRequest
    from src.domain.exceptions import GenerationError, NSFWContentError, ModelNotLoadedError

    assert IVideoGenerator is not None
    assert GenerationError is not None
    assert NSFWContentError is not None
    assert ModelNotLoadedError is not None

    print("✅ Domain layer imports successfully")


def test_config_creation():
    """Test configuration creation."""
    from src.services.generation.config import GenerationConfig
    
    config = GenerationConfig()
    
    # Verify default values
    assert config.T2V_MODEL_ID == "THUDM/CogVideoX-5b"
    assert config.I2V_MODEL_ID == "THUDM/CogVideoX-5b-I2V"
    assert config.ENABLE_SAFETY_CHECKER is True
    assert config.DEFAULT_GUIDANCE_SCALE == 6.0
    assert config.DEFAULT_NUM_INFERENCE_STEPS == 50
    
    print("✅ Configuration created successfully")


def test_models_validation():
    """Test data model validation."""
    from src.services.generation.models import GenJob, GenerationMode

    # Valid T2V job
    job = GenJob(prompts=["A test prompt"])
    assert job.id is not None
    assert len(job.prompts) == 1
    assert job.mode == GenerationMode.TEXT2VIDEO
    assert job.guidance_scale == 6.0
    assert job.num_inference_steps == 50
    
    # Test JSON serialization
    json_str = job.to_json()
    job_from_json = GenJob.from_json(json_str)
    assert job_from_json.id == job.id
    
    print("✅ Models validation passed")


def test_mode_enum():
    """Test GenerationMode enum."""
    from src.services.generation.models import GenerationMode

    assert GenerationMode.TEXT2VIDEO.value == "text2video"
    assert GenerationMode.IMAGE2VIDEO.value == "image2video"

    print("✅ Mode enum works correctly")


def test_no_opencv_import():
    """Verify that OpenCV is not imported in generation modules."""
    import src.services.generation.engines.text2video

    # Check that cv2 is not in sys.modules (should not be imported)
    assert 'cv2' not in sys.modules, "OpenCV should not be imported in generation modules"
    
    print("✅ OpenCV not imported (good for isolation)")


def test_no_paddleocr_import():
    """Verify that PaddleOCR is not imported in generation modules."""
    import src.services.generation.engines.text2video

    # Check that paddleocr is not in sys.modules
    assert 'paddleocr' not in sys.modules, "PaddleOCR should not be imported in generation modules"
    
    print("✅ PaddleOCR not imported (good for isolation)")


if __name__ == "__main__":
    print("Running generation module import tests...")
    print("-" * 60)

    test_import_generation_modules()
    test_import_domain_layer()
    test_config_creation()
    test_models_validation()
    test_mode_enum()
    test_no_opencv_import()
    test_no_paddleocr_import()
    
    print("-" * 60)
    print("✅ All import tests passed!")
