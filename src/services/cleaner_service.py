import tempfile
import shutil
import cv2
import numpy as np
import os
from pathlib import Path
from src.shared.logging import get_logger

from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter

# Import tunable configuration constants
from src.infrastructure.processors import subtitle_removal_config as SRC

logger = get_logger(__name__)

class SubtitleRemoverService:
    """
    Dynamic ROI-Based Subtitle Cleaner with VRAM Adaptation.

    Features:
    1. **ROI Format Support** (Backward Compatible):
       - ROI format: "x,y,w,h" (normalized 0.0-1.0 coordinates, where x,y is position and w,h is size)
       - Percentage presets: "bottom" (60%), "top" (60%), "full" (100%)
       - Single float: 0.6 = bottom 60% of screen

    2. **VRAM-Adaptive Kernel Sizing**:
       - <8GB VRAM (RTX 3060):  30x30 kernel
       - 8-16GB VRAM (RTX 3080): 40x40 kernel
       - >16GB VRAM (RTX 4090/5090): 45x45 kernel

    3. **Optional Debug Mode** (off by default):
       - Saves diagnostic images showing OCR detections, ROI boundaries, masks
       - Controlled via --debug CLI flag or DEBUG_SUBTITLE_REMOVAL env var

    Supported GPU: RTX 3060 - RTX 5090 (6GB - 24GB VRAM)
    """

    # Default ROI: bottom 60% of screen (covers subtitles slightly below center)
    DEFAULT_ROI_FACTOR = 0.6

    def __init__(self, mask_service, inpainter, lang='ru', roi_factor=None, debug=None):
        # CRITICAL: Subtitle removal requires GPU for OCR and ProPainter inpainting
        # CPU processing would take hours instead of minutes
        from src.infrastructure.utils.gpu_utils import require_gpu
        require_gpu("subtitle removal")

        self.inpainter = inpainter
        
        # Обработка языков
        if isinstance(lang, str):
            langs = [l.strip() for l in lang.split(',')]
        else:
            langs = lang if isinstance(lang, list) else ['en']
        if 'en' not in langs: langs.append('en')
            
        self.ocr_langs = langs
        self.ocr = PaddleWrapper(lang=self.ocr_langs, use_gpu=True)
        
        # Debug mode: off by default, enable via --debug flag or DEBUG_SUBTITLE_REMOVAL=1
        if debug is None:
            debug = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'
        self.debug_mode = debug

        # Parse ROI parameter (BACKWARD COMPATIBLE)
        self._parse_roi(roi_factor)

        # VRAM-adaptive kernel sizing
        self._kernel_size = self._detect_optimal_kernel_size()

        # Statistics for logging
        self._stats = {
            'total_detections': 0,
            'total_kept': 0,
            'total_filtered': 0,
            'frames_with_text': 0
        }

        roi_desc = self._get_roi_description()
        logger.info(f"SubtitleRemoverService initialized:")
        logger.info(f"  - ROI: {roi_desc}")
        logger.info(f"  - Dilation kernel: {self._kernel_size}x{self._kernel_size}")
        logger.info(f"  - Debug mode: {'ON' if self.debug_mode else 'OFF'}")

    def _parse_roi(self, roi_factor):
        """
        Parse ROI parameter with backward compatibility.
        Supports:
        - ROI format: "x,y,w,h" (normalized 0.0-1.0 coordinates, where x,y is position and w,h is size)
        - Presets: "bottom", "top", "full"
        - Single float: 0.6 (bottom 60%)
        """
        if roi_factor is None:
            # Default: bottom 60%
            self.roi_mode = 'percentage'
            self.roi_height_factor = self.DEFAULT_ROI_FACTOR
            self.roi_bbox = None
            return

        if isinstance(roi_factor, str):
            # Check if it's a ROI format (contains commas)
            if ',' in roi_factor:
                try:
                    parts = [float(x.strip()) for x in roi_factor.split(',')]
                    if len(parts) == 4:
                        # Parse as x,y,w,h format
                        x, y, w, h = parts

                        # Validate ranges
                        if all(0.0 <= v <= 1.0 for v in [x, y, w, h]):
                            # Additional validation: ensure box has non-zero area
                            if w > 0 and h > 0:
                                # Convert x,y,w,h to x1,y1,x2,y2 for internal use
                                x1 = x
                                y1 = y
                                x2 = x + w
                                y2 = y + h

                                # Clamp to [0, 1] range
                                x2 = min(x2, 1.0)
                                y2 = min(y2, 1.0)

                                self.roi_mode = 'bbox'
                                self.roi_bbox = (x1, y1, x2, y2)
                                # Convert bbox to equivalent height factor for filtering
                                # Use y1 as the top boundary (text below y1 is kept)
                                self.roi_height_factor = 1.0 - y1
                                logger.info(f"✅ ROI: x={x:.2f}, y={y:.2f}, w={w:.2f}, h={h:.2f} → "
                                          f"bbox ({x1:.2f},{y1:.2f},{x2:.2f},{y2:.2f})")
                                return
                            else:
                                logger.error(f"❌ Invalid ROI: zero-area region {roi_factor}")
                                logger.error(f"   Parsed: x={x:.2f}, y={y:.2f}, w={w:.2f}, h={h:.2f}")
                                logger.error(f"   Requirements: w > 0 and h > 0")
                                logger.error(f"   Using default ROI (bottom 60%)")
                        else:
                            logger.error(f"❌ Invalid ROI: coordinates must be in range [0.0, 1.0]: {roi_factor}")
                            logger.error(f"   Using default ROI (bottom 60%)")
                except ValueError as e:
                    logger.error(f"❌ Failed to parse ROI: {roi_factor}")
                    logger.error(f"   Error: {e}")
                    logger.error(f"   Expected format: 'x,y,w,h' (example: '0.0,0.5,1.0,0.4')")
                    logger.error(f"   Using default ROI (bottom 60%)")

            # Check for preset strings
            roi_lower = roi_factor.lower()
            if roi_lower == "full":
                self.roi_mode = 'percentage'
                self.roi_height_factor = 1.0
                self.roi_bbox = None
            elif roi_lower == "bottom":
                self.roi_mode = 'percentage'
                self.roi_height_factor = self.DEFAULT_ROI_FACTOR
                self.roi_bbox = None
            elif roi_lower == "top":
                self.roi_mode = 'percentage'
                self.roi_height_factor = 0.6  # Top 60% (от 0 до 0.6 по высоте)
                self.roi_bbox = None
            else:
                # Try to parse as single float
                try:
                    self.roi_mode = 'percentage'
                    self.roi_height_factor = float(roi_factor)
                    self.roi_bbox = None
                except ValueError:
                    logger.warning(f"Invalid ROI format: {roi_factor}, using default")
                    self.roi_mode = 'percentage'
                    self.roi_height_factor = self.DEFAULT_ROI_FACTOR
                    self.roi_bbox = None
        else:
            # Numeric value
            self.roi_mode = 'percentage'
            self.roi_height_factor = float(roi_factor) if roi_factor else self.DEFAULT_ROI_FACTOR
            self.roi_bbox = None

    def _get_roi_description(self) -> str:
        """Get human-readable ROI description for logging."""
        if self.roi_mode == 'bbox':
            x1, y1, x2, y2 = self.roi_bbox
            w = x2 - x1
            h = y2 - y1
            return f"Custom ROI (x={x1:.2f}, y={y1:.2f}, w={w:.2f}, h={h:.2f})"
        elif self.roi_height_factor >= 0.99:
            return "Full screen (no filtering)"
        else:
            pct = int(self.roi_height_factor * 100)
            return f"Bottom {pct}% of screen"

    def _detect_optimal_kernel_size(self) -> int:
        """
        Detect optimal dilation kernel size based on available VRAM.
        Can be overridden with FORCE_KERNEL_SIZE environment variable.

        Returns:
            Kernel size from config (default: 30, 40, or 45 based on VRAM)
        """
        try:
            import torch
            if not torch.cuda.is_available():
                logger.info(f"No CUDA available, using conservative kernel size ({SRC.KERNEL_SIZE_LOW_VRAM}x{SRC.KERNEL_SIZE_LOW_VRAM})")
                return SRC.KERNEL_SIZE_LOW_VRAM

            # Get total VRAM in GB
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = vram_bytes / (1024 ** 3)

            # Use config helper function (supports FORCE_KERNEL_SIZE env var)
            kernel_size = SRC.get_kernel_size_for_vram(vram_gb)

            logger.info(f"Detected {vram_gb:.1f}GB VRAM → using {kernel_size}x{kernel_size} kernel")
            return kernel_size

        except Exception as e:
            logger.warning(f"Failed to detect VRAM: {e}, using default {SRC.KERNEL_SIZE_LOW_VRAM}x{SRC.KERNEL_SIZE_LOW_VRAM} kernel")
            return SRC.KERNEL_SIZE_LOW_VRAM

    def _enhance_image_for_ocr(self, img: np.ndarray) -> np.ndarray:
        """
        CLAHE enhancement: pulls out hidden text by enhancing local contrast.
        Parameters controlled by SRC.CLAHE_CLIP_LIMIT and SRC.CLAHE_TILE_GRID_SIZE
        """
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(
                clipLimit=SRC.CLAHE_CLIP_LIMIT,
                tileGridSize=SRC.CLAHE_TILE_GRID_SIZE
            )
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return final
        except Exception:
            return img

    def _is_box_in_roi(self, box, img_width, img_height):
        """
        Проверяет, попадает ли центр текста в ROI.
        Returns: (is_in_roi: bool, center_x: float, center_y: float, roi_limit: float)
        """
        points = np.array(box, dtype=np.int32)
        center_x = np.mean(points[:, 0])
        center_y = np.mean(points[:, 1])
        
        # Full screen mode - no filtering
        if self.roi_height_factor >= 0.99 and self.roi_mode != 'bbox':
            return True, center_x, center_y, 0

        # Bounding box mode
        if self.roi_mode == 'bbox':
            x1, y1, x2, y2 = self.roi_bbox
            # Convert normalized coordinates to pixels
            x1_px = x1 * img_width
            y1_px = y1 * img_height
            x2_px = x2 * img_width
            y2_px = y2 * img_height

            # Check if center is inside bounding box
            is_in = (x1_px <= center_x <= x2_px) and (y1_px <= center_y <= y2_px)
            return is_in, center_x, center_y, y1_px

        # Percentage mode (default)
        # Граница: Высота * (1 - 0.6) = Точка начала нижних 60%
        roi_limit = img_height * (1.0 - self.roi_height_factor)
        is_in = center_y > roi_limit

        return is_in, center_x, center_y, roi_limit

    def _merge_detections(self, bboxes1: list, bboxes2: list) -> list:
        """
        Merge detections from two OCR passes, removing duplicates by IoU.
        Uses SRC.OCR_DUPLICATE_IOU_THRESHOLD to determine duplicates.
        """
        if not bboxes1:
            return bboxes2 or []
        if not bboxes2:
            return bboxes1

        merged = list(bboxes1)

        for bbox2 in bboxes2:
            is_duplicate = False
            pts2 = np.array(bbox2['points'])
            x2_min, y2_min = pts2.min(axis=0)
            x2_max, y2_max = pts2.max(axis=0)

            for bbox1 in bboxes1:
                pts1 = np.array(bbox1['points'])
                x1_min, y1_min = pts1.min(axis=0)
                x1_max, y1_max = pts1.max(axis=0)

                # Calculate IoU
                inter_x1 = max(x1_min, x2_min)
                inter_y1 = max(y1_min, y2_min)
                inter_x2 = min(x1_max, x2_max)
                inter_y2 = min(y1_max, y2_max)

                if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                    area1 = (x1_max - x1_min) * (y1_max - y1_min)
                    area2 = (x2_max - x2_min) * (y2_max - y2_min)
                    iou = inter_area / (area1 + area2 - inter_area + 1e-6)

                    # Use configurable IoU threshold
                    if iou > SRC.OCR_DUPLICATE_IOU_THRESHOLD:
                        is_duplicate = True
                        break

            if not is_duplicate:
                merged.append(bbox2)

        return merged

    def process(self, input_path, output_path: Path, **kwargs):
        logger.info(f"Removing subtitles from {input_path}")
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                mask_dir = temp_path / "masks"
                mask_dir.mkdir()
                
                frames_dir = None
                
                # 1. Подготовка кадров
                if isinstance(input_path, list):
                    frames_dir = temp_path / "input_frames"
                    frames_dir.mkdir()
                    for i, frame_path in enumerate(input_path):
                        p = Path(frame_path)
                        shutil.copy(p, frames_dir / f"frame_{i:06d}{p.suffix}")
                else:
                    input_path = Path(input_path)
                    if input_path.is_dir():
                        frames_dir = input_path
                    else:
                        from src.infrastructure.media.ffmpeg import FFmpegExtractor
                        extractor = FFmpegExtractor()
                        frames_dir = temp_path / "extracted_frames"
                        frames_dir.mkdir()
                        extractor.extract_frames(input_path, frames_dir)

                # 2. Генерация масок с учетом ROI
                self._generate_roi_masks(frames_dir, mask_dir)
                
                # 3. Inpainting
                result_path = self.inpainter.process(frames_dir, mask_dir, output_path)
            
            class SimpleResult:
                def __init__(self, success=True, output_path=None):
                    self.success = success
                    self.output_path = output_path
            
            return SimpleResult(success=True, output_path=result_path)
            
        except Exception as e:
            logger.error(f"Subtitle removal failed: {e}", exc_info=True)
            class SimpleResult:
                def __init__(self, success=False, output_path=None, errors=None):
                    self.success = success
                    self.output_path = output_path
                    self.errors = [str(e)] if errors is None else errors
            return SimpleResult(success=False, output_path=None, errors=[str(e)])

    def _generate_roi_masks(self, frames_dir: Path, mask_dir: Path):
        """Generate binary masks with ROI filtering and detailed logging."""
        roi_desc = self._get_roi_description()
        logger.info(f"Generating masks (ROI: {roi_desc})...")

        frames = sorted(list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png")))
        if not frames:
            raise ValueError(f"No frames found in {frames_dir}")
        
        # Reset statistics
        self._stats = {
            'total_detections': 0,
            'total_kept': 0,
            'total_filtered': 0,
            'frames_with_text': 0,
            'confidence_min': 1.0,
            'confidence_max': 0.0,
            'confidence_sum': 0.0
        }

        total_frames = len(frames)
        # Use configurable progress logging interval
        log_interval = max(1, total_frames // (100 // SRC.PROGRESS_LOG_PERCENTAGE))

        # Use configurable OCR threshold from config
        logger.info(f"Using OCR confidence threshold: {SRC.OCR_CONFIDENCE_THRESHOLD}")
        if SRC.OCR_DUAL_PASS_ENABLED:
            logger.info("Dual-pass OCR enabled (enhanced + original)")

        for idx, frame_path in enumerate(frames):
            img = cv2.imread(str(frame_path))
            if img is None:
                continue

            h, w = img.shape[:2]
            mask = np.zeros((h, w), dtype=np.uint8)
            
            # А. Улучшаем для OCR
            enhanced_img = self._enhance_image_for_ocr(img)
            
            # Б. Агрессивная детекция: запускаем OCR на ОБОИХ изображениях и объединяем
            # Контролируется константой SRC.OCR_DUAL_PASS_ENABLED
            if SRC.OCR_DUAL_PASS_ENABLED:
                bboxes_enhanced = self.ocr.detect(enhanced_img, confidence_threshold=SRC.OCR_CONFIDENCE_THRESHOLD)
                bboxes_original = self.ocr.detect(img, confidence_threshold=SRC.OCR_CONFIDENCE_THRESHOLD)
                # Объединяем результаты (убираем дубликаты по IoU)
                bboxes = self._merge_detections(bboxes_enhanced, bboxes_original)
            else:
                # Single pass: только на улучшенном изображении
                bboxes = self.ocr.detect(enhanced_img, confidence_threshold=SRC.OCR_CONFIDENCE_THRESHOLD)

            if not bboxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue
            
            # Track confidence scores
            for bbox in bboxes:
                conf = bbox.get('confidence', 0)
                self._stats['confidence_min'] = min(self._stats['confidence_min'], conf)
                self._stats['confidence_max'] = max(self._stats['confidence_max'], conf)
                self._stats['confidence_sum'] += conf

            detected_count = len(bboxes)
            self._stats['total_detections'] += detected_count

            # В. ФИЛЬТРАЦИЯ ПО ROI (Отсекаем текст вне зоны субтитров)
            valid_boxes = []
            filtered_boxes = []
            for bbox in bboxes:
                is_in_roi, center_x, center_y, roi_limit = self._is_box_in_roi(bbox['points'], w, h)
                if is_in_roi:
                    valid_boxes.append(bbox)
                else:
                    filtered_boxes.append({
                        'text': bbox.get('text', '?')[:20],
                        'center_x': center_x,
                        'center_y': center_y,
                        'roi_limit': roi_limit
                    })

            kept_count = len(valid_boxes)
            filtered_count = detected_count - kept_count

            self._stats['total_kept'] += kept_count
            self._stats['total_filtered'] += filtered_count

            if kept_count > 0:
                self._stats['frames_with_text'] += 1

            # Debug log for frames with filtered boxes
            if filtered_count > 0 and logger.isEnabledFor(10):  # DEBUG level
                # Use configurable max examples count
                for fb in filtered_boxes[:SRC.DEBUG_MAX_FILTERED_EXAMPLES]:
                    logger.debug(f"[Frame {idx}] Filtered: '{fb['text']}' "
                               f"center=({fb['center_x']:.0f},{fb['center_y']:.0f}) "
                               f"roi_limit={fb['roi_limit']:.0f}")

            if not valid_boxes:
                cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
                continue

            # Г. Рисуем маску с расширенными боксами (catch glow/shadows)
            # Используем конфигурируемые значения расширения
            for bbox in valid_boxes:
                points = np.array(bbox['points'], dtype=np.int32)
                x_min, y_min = points.min(axis=0)
                x_max, y_max = points.max(axis=0)

                # Use configurable expansion values
                x_min = max(0, x_min - SRC.BBOX_EXPAND_HORIZONTAL)
                x_max = min(w, x_max + SRC.BBOX_EXPAND_HORIZONTAL)
                y_min = max(0, y_min - SRC.BBOX_EXPAND_VERTICAL)
                y_max = min(h, y_max + SRC.BBOX_EXPAND_VERTICAL)

                expanded_points = np.array([[x_min, y_min], [x_max, y_min],
                                          [x_max, y_max], [x_min, y_max]], dtype=np.int32)
                cv2.fillPoly(mask, [expanded_points], 255)

            # Д. VRAM-Adaptive Dilation + Morphological Closing
            # Все параметры контролируются конфигурационными константами
            kernel = np.ones((self._kernel_size, self._kernel_size), np.uint8)

            # Dilation: захватываем свечение
            mask = cv2.dilate(mask, kernel, iterations=SRC.DILATION_ITERATIONS_INITIAL)

            # Morphological closing: заполняем пробелы между буквами
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=SRC.MORPHOLOGICAL_CLOSING_ITERATIONS)

            # Final dilation pass
            mask = cv2.dilate(mask, kernel, iterations=SRC.DILATION_ITERATIONS_FINAL)

            cv2.imwrite(str(mask_dir / f"{frame_path.stem}.png"), mask)
            
            # Progress logging
            if (idx + 1) % log_interval == 0:
                progress = (idx + 1) / total_frames * 100
                logger.info(f"Mask generation progress: {progress:.0f}% ({idx + 1}/{total_frames})")

            # GPU memory cleanup (configurable interval)
            if (idx + 1) % SRC.GPU_CLEANUP_INTERVAL == 0:
                try:
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    pass

        # Final summary
        avg_conf = (self._stats['confidence_sum'] / self._stats['total_detections']
                   if self._stats['total_detections'] > 0 else 0)

        logger.info(f"Mask generation complete:")
        logger.info(f"  - Frames processed: {total_frames}")
        logger.info(f"  - Frames with text: {self._stats['frames_with_text']}")
        logger.info(f"  - Total detections: {self._stats['total_detections']}")
        logger.info(f"  - Kept (in ROI): {self._stats['total_kept']}")
        logger.info(f"  - Filtered (outside ROI): {self._stats['total_filtered']}")
        if self._stats['total_detections'] > 0:
            logger.info(f"  - Confidence: min={self._stats['confidence_min']:.2f}, "
                       f"max={self._stats['confidence_max']:.2f}, avg={avg_conf:.2f}")

# Заглушка
class LegacySubtitleRemoverService:
    def __init__(self, *args, **kwargs):
        pass
    def process(self, request):
        raise NotImplementedError("Legacy Service Removed")
