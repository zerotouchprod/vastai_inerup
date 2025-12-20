import os
os.environ['DISABLE_MODEL_SOURCE_CHECK'] = 'True'

import sys
sys.path.insert(0, '.')

print('Testing PaddleOCR with parameters from mask_service...')

try:
    from paddleocr import PaddleOCR
    print('PaddleOCR imported')
    
    ocr = PaddleOCR(
        lang='ru',
        use_textline_orientation=True,
        det_model_dir=None,
        rec_model_dir=None,
        cls_model_dir=None,
        text_det_thresh=0.1,
        text_det_box_thresh=0.1,
        text_det_unclip_ratio=2.5,
        text_det_limit_side_len=960,
        text_det_limit_type='max',
        text_rec_score_thresh=0.01,
    )
    print('SUCCESS: OCR initialized without errors')
    
    # Quick test with a small black image
    import cv2
    import numpy as np
    test_img = np.zeros((100, 100, 3), dtype=np.uint8)
    result = ocr.ocr(test_img, cls=True, rec=True)
    print(f'OCR result on black image: {result}')
    
except Exception as e:
    print(f'ERROR: {e}')
    import traceback
    traceback.print_exc()
