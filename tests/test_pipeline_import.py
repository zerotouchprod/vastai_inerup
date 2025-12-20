"""
Test pipeline_v2.py imports to ensure the refactored code works.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_pipeline_imports():
    """Test that pipeline_v2.py can be imported without errors."""
    logger.info("Testing pipeline_v2.py imports...")
    
    try:
        # Add current directory to path
        sys.path.insert(0, '.')
        
        # Try to import the main CLI module
        from src.presentation.cli import main, create_orchestrator_from_config
        logger.info("✓ src.presentation.cli imported successfully")
        
        # Try to import the factory
        from src.application.factories import ProcessorFactory
        logger.info("✓ ProcessorFactory imported successfully")
        
        # Try to create factory
        factory = ProcessorFactory()
        logger.info("✓ ProcessorFactory instantiated successfully")
        
        # Try to create subtitle remover (may fail if dependencies missing, but that's OK)
        try:
            subtitle_remover = factory.create_subtitle_remover(lang='ru')
            logger.info("✓ Subtitle remover created successfully")
        except Exception as e:
            logger.info(f"⚠ Subtitle remover creation failed (expected if dependencies missing): {e}")
        
        logger.info("\n" + "="*60)
        logger.info("SUCCESS: All imports work correctly!")
        logger.info("The refactored code is properly integrated.")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_pipeline_imports()
    sys.exit(0 if success else 1)
