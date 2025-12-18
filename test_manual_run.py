"""
Manual test script for refactored subtitle removal module.
"""

import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_config_module():
    """Test configuration module."""
    logger.info("Testing configuration module...")
    
    try:
        from src.core.config import get_config, AppConfig
        
        # Test default config
        config = get_config()
        logger.info(f"Default config: OCR_LANG={config.OCR_LANG}, MASK_DILATION={config.MASK_DILATION}")
        
        # Test creating new config
        test_config = AppConfig()
        logger.info(f"Test config created: PROPAINTER_ROOT={test_config.PROPAINTER_ROOT}")
        
        logger.info("✓ Configuration module test passed")
        return True
        
    except Exception as e:
        logger.error(f"Configuration module test failed: {e}")
        return False


def test_domain_models():
    """Test domain models."""
    logger.info("Testing domain models...")
    
    try:
        from src.domain.models import InpaintingRequest, ProcessingResult, ProcessingStats
        
        # Test InpaintingRequest
        request = InpaintingRequest(
            input_dir=Path("/tmp/input"),
            output_dir=Path("/tmp/output")
        )
        logger.info(f"InpaintingRequest created: {request}")
        
        # Test ProcessingResult
        stats = ProcessingStats(
            frames_total=100,
            duration_seconds=10.5,
            device_used="cuda"
        )
        
        result = ProcessingResult(
            success=True,
            output_path=Path("/tmp/output"),
            frames_processed=100,
            stats=stats
        )
        logger.info(f"ProcessingResult created: {result}")
        
        logger.info("✓ Domain models test passed")
        return True
        
    except Exception as e:
        logger.error(f"Domain models test failed: {e}")
        return False


def test_infrastructure_modules():
    """Test infrastructure modules (mocked)."""
    logger.info("Testing infrastructure modules (with mocks)...")
    
    try:
        # Test OCR wrapper import
        from src.infrastructure.ocr.paddle_wrapper import ThreadSafeOCR
        logger.info(f"ThreadSafeOCR imported: {ThreadSafeOCR}")
        
        # Test ProPainter loader import
        from src.infrastructure.inpainting.propainter_loader import ProPainterLoader
        logger.info(f"ProPainterLoader imported: {ProPainterLoader}")
        
        # Test ProPainter adapter import
        from src.infrastructure.inpainting.propainter_adapter import ProPainterModelAdapter
        logger.info(f"ProPainterModelAdapter imported: {ProPainterModelAdapter}")
        
        logger.info("✓ Infrastructure modules test passed")
        return True
        
    except Exception as e:
        logger.error(f"Infrastructure modules test failed: {e}")
        return False


def test_service_modules():
    """Test service modules."""
    logger.info("Testing service modules...")
    
    try:
        # Test MaskGeneratorService
        from src.services.mask_service import MaskGeneratorService
        logger.info(f"MaskGeneratorService imported: {MaskGeneratorService}")
        
        # Test SubtitleRemoverService
        from src.services.cleaner_service import SubtitleRemoverService
        logger.info(f"SubtitleRemoverService imported: {SubtitleRemoverService}")
        
        # Test wrapper
        from src.services.wrapper import SubtitleRemoverProPainterWrapper
        logger.info(f"SubtitleRemoverProPainterWrapper imported: {SubtitleRemoverProPainterWrapper}")
        
        logger.info("✓ Service modules test passed")
        return True
        
    except Exception as e:
        logger.error(f"Service modules test failed: {e}")
        return False


def test_wrapper_interface():
    """Test wrapper interface for backward compatibility."""
    logger.info("Testing wrapper interface...")
    
    try:
        from src.services.wrapper import SubtitleRemoverProPainterWrapper
        
        # Create wrapper instance
        wrapper = SubtitleRemoverProPainterWrapper(
            lang="en",
            mask_dilation=12
        )
        
        logger.info(f"Wrapper created: {wrapper}")
        logger.info(f"Wrapper supports GPU: {wrapper.supports_gpu()}")
        
        # Note: We can't test actual processing without real dependencies
        # but we can verify the interface exists
        logger.info("✓ Wrapper interface test passed")
        return True
        
    except Exception as e:
        logger.error(f"Wrapper interface test failed: {e}")
        return False


def test_structure():
    """Test overall project structure."""
    logger.info("Testing project structure...")
    
    required_dirs = [
        "src/core",
        "src/domain", 
        "src/infrastructure/ocr",
        "src/infrastructure/inpainting",
        "src/infrastructure/utils",
        "src/services"
    ]
    
    required_files = [
        "src/core/config.py",
        "src/core/exceptions.py",
        "src/core/device.py",
        "src/domain/models.py",
        "src/infrastructure/ocr/paddle_wrapper.py",
        "src/infrastructure/inpainting/propainter_loader.py",
        "src/infrastructure/inpainting/propainter_adapter.py",
        "src/services/mask_service.py",
        "src/services/cleaner_service.py",
        "src/services/wrapper.py"
    ]
    
    all_passed = True
    
    # Check directories
    for dir_path in required_dirs:
        if Path(dir_path).exists():
            logger.info(f"✓ Directory exists: {dir_path}")
        else:
            logger.error(f"✗ Directory missing: {dir_path}")
            all_passed = False
    
    # Check files
    for file_path in required_files:
        if Path(file_path).exists():
            logger.info(f"✓ File exists: {file_path}")
        else:
            logger.error(f"✗ File missing: {file_path}")
            all_passed = False
    
    return all_passed


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Starting manual tests for refactored subtitle removal module")
    logger.info("=" * 60)
    
    tests = [
        ("Project Structure", test_structure),
        ("Configuration Module", test_config_module),
        ("Domain Models", test_domain_models),
        ("Infrastructure Modules", test_infrastructure_modules),
        ("Service Modules", test_service_modules),
        ("Wrapper Interface", test_wrapper_interface)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        logger.info(f"\n{'='*40}")
        logger.info(f"Test: {test_name}")
        logger.info(f"{'='*40}")
        
        try:
            success = test_func()
            results.append((test_name, success))
            
            if success:
                logger.info(f"✓ {test_name}: PASSED")
            else:
                logger.error(f"✗ {test_name}: FAILED")
                
        except Exception as e:
            logger.error(f"✗ {test_name}: ERROR - {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*60}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "PASSED" if success else "FAILED"
        logger.info(f"{test_name:30} {status}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✓ All tests passed! Refactoring successful.")
        return 0
    else:
        logger.error(f"✗ {total - passed} tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
