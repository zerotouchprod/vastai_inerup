import cv2
import numpy as np
from pathlib import Path
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.shared.logging import get_logger

logger = get_logger(__name__)

class MaskGeneratorService:
    def __init__(self, lang: str = 'en', use_gpu: bool = True, **kwargs):
        # Инициализируем наш "Paranoid" OCR
        self.ocr = PaddleWrapper(lang=lang, use_gpu=use_gpu)
        # Размер ядра для расширения маски (fix purple rim)
        self.dilation_kernel_size = kwargs.get('mask_dilation', 10)
        # ROI (Region of Interest) для ограничения зоны детекции
        self.roi_str = kwargs.get('roi_str', None)
        if self.roi_str:
            logger.info(f"MaskGeneratorService initialized with ROI: {self.roi_str}")

    def generate_masks(self, frames_dir: Path, output_dir: Path) -> Path:
        """
        Generates masks for all images in frames_dir and saves them to output_dir.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        
        logger.info(f"Generating masks for {len(frames)} frames...")
        
        for frame_path in frames:
            img = cv2.imread(str(frame_path))
            if img is None: continue
            
            # 1. OCR Detection with adaptive threshold
            # Lower threshold for expected subtitle zones (bottom/top), higher for full-screen
            if self.roi_str in ('bottom', 'top'):
                confidence_threshold = 0.005  # Aggressive in subtitle zones
            elif self.roi_str == 'full':
                confidence_threshold = 0.05   # Conservative full-screen (reduce false positives)
            else:
                confidence_threshold = 0.01   # Default paranoid mode

            # PaddleWrapper сам вернет всё, что нашел
            # Pass roi_str for pre-cropping optimization (reduces OCR time by 50-70%)
            bboxes = self.ocr.detect(img, confidence_threshold=confidence_threshold, roi_str=self.roi_str)

            # 2. Draw basic mask
            mask = np.zeros(img.shape[:2], dtype=np.uint8)
            for bbox in bboxes:
                points = np.array(bbox['points'], dtype=np.int32)
                cv2.fillPoly(mask, [points], 255)
            
            # 3. DILATION (Critical Fix for artifacts)
            if self.dilation_kernel_size > 0:
                kernel = np.ones((self.dilation_kernel_size, self.dilation_kernel_size), np.uint8)
                mask = cv2.dilate(mask, kernel, iterations=1)
            
            # 4. Apply ROI constraint if provided (Mask Guillotine)
            if self.roi_str:
                from src.infrastructure.image_processing.geometry import resolve_roi
                h, w = img.shape[:2]
                x, y, roi_w, roi_h = resolve_roi(self.roi_str, w, h)

                # Create ROI mask (white rectangle on black canvas)
                roi_mask = np.zeros_like(mask)
                cv2.rectangle(roi_mask, (x, y), (x + roi_w, y + roi_h), 255, -1)

                # Apply hard constraint: keep mask only inside ROI
                mask = cv2.bitwise_and(mask, roi_mask)

                # Log statistics for debugging
                total_pixels = h * w
                roi_pixels = np.sum(roi_mask > 0)
                mask_pixels = np.sum(mask > 0)
                logger.debug(
                    f"ROI constraint applied: ROI covers {roi_pixels/total_pixels*100:.1f}% of frame, "
                    f"final mask covers {mask_pixels/total_pixels*100:.1f}%"
                )

            # 5. Save
            cv2.imwrite(str(output_dir / frame_path.name), mask)
            
        return output_dir
