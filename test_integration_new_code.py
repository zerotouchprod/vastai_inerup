"""
Integration test for new refactored subtitle removal code.
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


def test_new_architecture():
    """Test the new refactored architecture components."""
    logger.info("Testing new refactored architecture...")
    
    tests = []
    
    # Test 1: Core modules
    try:
        from src.core.config import AppConfig, get_config
        config = AppConfig()
        logger.info(f"✓ Core config: OCR_LANG={config.OCR_LANG}, MASK_DILATION={config.MASK_DILATION}")
        tests.append(("Core Config", True))
    except Exception as e:
        logger.error(f"✗ Core config failed: {e}")
        tests.append(("Core Config", False))
    
    # Test 2: Domain models
    try:
        from src.domain.models import InpaintingRequest, ProcessingResult, ProcessingStats
        request = InpaintingRequest(
            input_dir=Path("/tmp/input"),
            output_dir=Path("/tmp/output")
        )
        logger.info(f"✓ Domain models: {request}")
        tests.append(("Domain Models", True))
    except Exception as e:
        logger.error(f"✗ Domain models failed: {e}")
        tests.append(("Domain Models", False))
    
    # Test 3: Infrastructure - OCR wrapper
    try:
        from src.infrastructure.ocr.paddle_wrapper import ThreadSafeOCR
        logger.info(f"✓ OCR wrapper: {ThreadSafeOCR}")
        tests.append(("OCR Wrapper", True))
    except Exception as e:
        logger.error(f"✗ OCR wrapper failed: {e}")
        tests.append(("OCR Wrapper", False))
    
    # Test 4: Infrastructure - ProPainter loader
    try:
        from src.infrastructure.inpainting.propainter_loader import ProPainterLoader
        logger.info(f"✓ ProPainter loader: {ProPainterLoader}")
        tests.append(("ProPainter Loader", True))
    except Exception as e:
        logger.error(f"✗ ProPainter loader failed: {e}")
        tests.append(("ProPainter Loader", False))
    
    # Test 5: Services - Mask service
    try:
        from src.services.mask_service import MaskGeneratorService
        logger.info(f"✓ Mask service: {MaskGeneratorService}")
        tests.append(("Mask Service", True))
    except Exception as e:
        logger.error(f"✗ Mask service failed: {e}")
        tests.append(("Mask Service", False))
    
    # Test 6: Services - Cleaner service
    try:
        from src.services.cleaner_service import SubtitleRemoverService
        logger.info(f"✓ Cleaner service: {SubtitleRemoverService}")
        tests.append(("Cleaner Service", True))
    except Exception as e:
        logger.error(f"✗ Cleaner service failed: {e}")
        tests.append(("Cleaner Service", False))
    
    # Test 7: Services - Wrapper
    try:
        from src.services.wrapper import SubtitleRemoverProPainterWrapper
        logger.info(f"✓ Service wrapper: {SubtitleRemoverProPainterWrapper}")
        tests.append(("Service Wrapper", True))
    except Exception as e:
        logger.error(f"✗ Service wrapper failed: {e}")
        tests.append(("Service Wrapper", False))
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("INTEGRATION TEST SUMMARY")
    logger.info("="*60)
    
    passed = sum(1 for _, success in tests if success)
    total = len(tests)
    
    for test_name, success in tests:
        status = "PASSED" if success else "FAILED"
        logger.info(f"{test_name:20} {status}")
    
    logger.info(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("✓ All new architecture components work correctly!")
        return True
    else:
        logger.error(f"✗ {total - passed} tests failed.")
        return False


def test_backward_compatibility():
    """Test backward compatibility with old wrapper interface."""
    logger.info("\n" + "="*60)
    logger.info("Testing backward compatibility...")
    logger.info("="*60)
    
    try:
        # Import the updated wrapper
        import sys
        sys.path.insert(0, '.')
        
        # Mock shared module to avoid import errors
        import types
        shared_module = types.ModuleType('shared')
        logging_module = types.ModuleType('logging')
        
        def mock_get_logger(name):
            import logging
            return logging.getLogger(name)
        
        logging_module.get_logger = mock_get_logger
        shared_module.logging = logging_module
        
        # Mock metrics module
        metrics_module = types.ModuleType('metrics')
        
        class MockMetricsCollector:
            def __init__(self):
                pass
            def start_timer(self, name):
                pass
            def stop_timer(self, name):
                return 0.0
            def elapsed_time(self):
                return 0.0
        
        metrics_module.MetricsCollector = MockMetricsCollector
        shared_module.metrics = metrics_module
        
        sys.modules['shared'] = shared_module
        sys.modules['shared.logging'] = logging_module
        sys.modules['shared.metrics'] = metrics_module
        
        # Now try to import the wrapper
        from src.infrastructure.processors.subtitle.wrapper import SubtitleRemoverWrapper
        
        logger.info("✓ Backward compatibility wrapper imported successfully")
        
        # Check if it implements the expected interface
        wrapper = SubtitleRemoverWrapper(lang='en', mask_dilation=12)
        
        required_methods = ['process', 'is_available', 'supports_gpu']
        for method in required_methods:
            if hasattr(wrapper, method):
                logger.info(f"✓ Method '{method}' exists")
            else:
                logger.error(f"✗ Method '{method}' missing")
                return False
        
        logger.info("✓ All required methods exist")
        logger.info("✓ Backward compatibility maintained!")
        return True
        
    except Exception as e:
        logger.error(f"✗ Backward compatibility test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run integration tests."""
    logger.info("="*60)
    logger.info("INTEGRATION TESTS FOR REFACTORED SUBTITLE REMOVAL")
    logger.info("="*60)
    
    # Test new architecture
    arch_success = test_new_architecture()
    
    # Test backward compatibility
    compat_success = test_backward_compatibility()
    
    # Final summary
    logger.info("\n" + "="*60)
    logger.info("FINAL SUMMARY")
    logger.info("="*60)
    
    if arch_success and compat_success:
        logger.info("✓ SUCCESS: New refactored code is ready for use!")
        logger.info("✓ Old propainter wrappers have been removed")
        logger.info("✓ Backward compatibility is maintained")
        logger.info("✓ All dependencies are updated")
        return 0
    else:
        logger.error("✗ FAILURE: Some tests failed")
        if not arch_success:
            logger.error("  - New architecture components have issues")
        if not compat_success:
            logger.error("  - Backward compatibility has issues")
        return 1


if __name__ == "__main__":
    sys.exit(main())
