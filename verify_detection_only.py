import sys
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_detection_only():
    """Test that detection-only OCR call works and returns boxes."""
    from src.services.mask_service import MaskGeneratorService

    with patch('src.services.mask_service.PADDLE_AVAILABLE', True):
        with patch('src.services.mask_service.PaddleOCR') as MockPaddleOCR:
            # Mock OCR instance
            mock_instance = MagicMock()
            # Simulate detection-only result: list of boxes
            mock_instance.ocr.return_value = [[
                [[10, 10], [50, 10], [50, 30], [10, 30]],
                [[60, 60], [100, 60], [100, 80], [60, 80]]
            ]]
            MockPaddleOCR.return_value = mock_instance

            service = MaskGeneratorService(lang='en', use_gpu_for_ocr=False)
            assert service.ocr is not None

            # Call process_image with a dummy image (mock cv2.imread)
            with patch('cv2.imread') as mock_imread:
                mock_imread.return_value = np.ones((100, 100, 3), dtype=np.uint8) * 255
                with patch('cv2.resize'):
                    with patch('cv2.cvtColor'):
                        with patch('cv2.bitwise_not'):
                            with patch('cv2.createCLAHE'):
                                # We'll just test that OCR is called with correct arguments
                                # Since we mock everything, we can't test full flow.
                                pass

            # Verify that ocr.ocr was called with det=True, rec=False, cls=False
            # Actually we need to call process_image with a numpy array to avoid file reading.
            # Let's directly test the OCR call using a mock image array.
            # We'll patch the internal methods to skip enhancement.
            with patch.object(service, '_enhance_variants') as mock_enhance:
                mock_enhance.return_value = [np.ones((200, 200, 3), dtype=np.uint8)]
                img = np.ones((100, 100, 3), dtype=np.uint8)
                masked, texts = service.process_image(img)
                # Check that ocr.ocr was called with correct parameters
                call_kwargs = mock_instance.ocr.call_args[1]
                assert call_kwargs.get('det') == True
                assert call_kwargs.get('rec') == False
                assert call_kwargs.get('cls') == False
                print("✅ Detection-only OCR call verified.")

def main():
    import numpy as np
    logging.basicConfig(level=logging.WARNING)
    try:
        test_detection_only()
        print("\n🎉 Detection-only mode test passed.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
