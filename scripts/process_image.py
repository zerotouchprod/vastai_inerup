#!/usr/bin/env python3
"""
CLI script for removing text from images using PaddleOCR + SAM 2 + OpenCV inpainting.
"""

import sys
import os
import argparse
import time
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import cv2
import numpy as np
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_wrapper import SAM2ImageWrapper
from src.shared.logging import get_logger

logger = get_logger(__name__)

def apply_roi(image: np.ndarray, roi_str: str):
    """
    Apply ROI to image for OCR detection.
    
    Args:
        image: Input image
        roi_str: ROI string (full, bottom, top, or x,y,w,h)
        
    Returns:
        Tuple of (cropped_image, offset_x, offset_y)
    """
    h, w = image.shape[:2]
    
    if roi_str == 'full':
        return image, 0, 0
        
    elif roi_str == 'bottom':
        # Take bottom 30%
        y_start = int(h * 0.7)
        cropped = image[y_start:h, 0:w]
        return cropped, 0, y_start
        
    elif roi_str == 'top':
        # Take top 30%
        y_end = int(h * 0.3)
        cropped = image[0:y_end, 0:w]
        return cropped, 0, 0
        
    else:
        # Parse custom coordinates "x,y,w,h" (0.0-1.0)
        try:
            parts = roi_str.split(',')
            if len(parts) != 4:
                raise ValueError(f"Invalid ROI format: {roi_str}. Expected 'x,y,w,h'")
            
            x = float(parts[0])
            y = float(parts[1])
            width = float(parts[2])
            height = float(parts[3])
            
            # Convert to pixel coordinates
            x_px = int(x * w)
            y_px = int(y * h)
            w_px = int(width * w)
            h_px = int(height * h)
            
            # Ensure coordinates are within bounds
            x_px = max(0, min(x_px, w - 1))
            y_px = max(0, min(y_px, h - 1))
            w_px = max(1, min(w_px, w - x_px))
            h_px = max(1, min(h_px, h - y_px))
            
            cropped = image[y_px:y_px+h_px, x_px:x_px+w_px]
            return cropped, x_px, y_px
            
        except Exception as e:
            logger.warning(f"Failed to parse ROI '{roi_str}': {e}. Using full image.")
            return image, 0, 0


def process_image(image_path: str, output_dir: str = None, debug: bool = False, 
                  subs_lang: str = 'en', roi: str = 'full', confidence: float = 0.6) -> str:
    """
    Process single image to remove text.
    
    Args:
        image_path: Path to input image
        output_dir: Output directory (default: same as input)
        debug: Save debug mask if True
        subs_lang: Language code for OCR (en, ru, ch, etc.)
        roi: Region of interest for text detection
        confidence: Confidence threshold for text detection (0.0-1.0)
        
    Returns:
        Path to processed image
    """
    start_time = time.time()
    
    # Validate input
    input_path = Path(image_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # Determine output path
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{input_path.stem}_cleaned{input_path.suffix}"
    else:
        output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"
    
    # Load image
    logger.info(f"Loading image: {input_path}")
    image = cv2.imread(str(input_path))
    if image is None:
        raise ValueError(f"Failed to load image: {input_path}")
    
    h, w = image.shape[:2]
    logger.info(f"Image size: {w}x{h}")
    logger.info(f"OCR language: {subs_lang}")
    logger.info(f"ROI: {roi}")
    
    # Step 1: Detect text with PaddleOCR (with ROI)
    logger.info("Step 1/3: Detecting text with PaddleOCR...")
    
    # Apply ROI for OCR detection
    ocr_image, offset_x, offset_y = apply_roi(image, roi)
    logger.info(f"ROI applied: offset_x={offset_x}, offset_y={offset_y}, size={ocr_image.shape[1]}x{ocr_image.shape[0]}")
    
    # Initialize OCR with specified language
    ocr = PaddleWrapper(lang=subs_lang, use_gpu=True)
    bboxes = ocr.detect_text(ocr_image, confidence_threshold=confidence)
    
    # Adjust bbox coordinates back to original image
    adjusted_bboxes = []
    for bbox in bboxes:
        x1, y1, x2, y2 = bbox
        adjusted_bboxes.append([
            x1 + offset_x,
            y1 + offset_y,
            x2 + offset_x,
            y2 + offset_y
        ])
    
    bboxes = adjusted_bboxes
    
    if not bboxes:
        logger.info("No text detected in image. Copying original image.")
        cv2.imwrite(str(output_path), image)
        elapsed = time.time() - start_time
        logger.info(f"Processing completed in {elapsed:.2f}s (no text found)")
        return str(output_path)
    
    logger.info(f"Detected {len(bboxes)} text regions")
    
    # Step 2: Generate precise mask with SAM 2
    logger.info("Step 2/3: Generating precise mask with SAM 2...")
    sam2 = SAM2ImageWrapper()
    mask = sam2.get_mask(image, bboxes)
    
    # Dilate mask slightly to ensure complete text removal
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    
    # Save debug mask if requested
    if debug:
        debug_mask_path = output_path.parent / f"{input_path.stem}_mask.png"
        cv2.imwrite(str(debug_mask_path), mask)
        logger.info(f"Debug mask saved: {debug_mask_path}")
    
    # Step 3: Inpaint using Telea algorithm
    logger.info("Step 3/3: Inpainting with OpenCV...")
    
    # Convert mask to required format (0 or 255)
    mask_uint8 = mask.astype(np.uint8)
    
    # Use Telea algorithm for inpainting
    result = cv2.inpaint(image, mask_uint8, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    
    # Save result
    cv2.imwrite(str(output_path), result)
    
    elapsed = time.time() - start_time
    logger.info(f"Processing completed in {elapsed:.2f}s")
    logger.info(f"Output saved: {output_path}")
    
    return str(output_path)

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Remove text from images using PaddleOCR + SAM 2 + OpenCV inpainting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --image test.jpg
  %(prog)s --image test.jpg --output ./results
  %(prog)s --image test.jpg --debug
        """
    )
    
    parser.add_argument(
        "--image",
        required=True,
        help="Path to input image"
    )
    
    parser.add_argument(
        "--output",
        help="Output directory (default: same as input)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug mask for verification"
    )
    
    parser.add_argument(
        "--subs-lang",
        type=str,
        default='ru',
        help='Language code for PaddleOCR (examples: en, ru, ch). Affects accuracy.'
    )
    
    parser.add_argument(
        "--roi",
        type=str,
        default='full',
        help='Region of interest for text detection. '
             'Presets: "bottom" (bottom 30%%), "top" (top 30%%), "full" (entire frame). '
             'Or coordinates "x,y,w,h" (0.0-1.0), e.g. "0,0.8,1,0.2" for bottom.'
    )
    
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.6,
        help="Confidence threshold for text detection (default: 0.6)"
    )
    
    args = parser.parse_args()
    
    try:
        # Process image
        output_path = process_image(
            image_path=args.image,
            output_dir=args.output,
            debug=args.debug,
            subs_lang=args.subs_lang,
            roi=args.roi,
            confidence=args.confidence
        )
        
        print(f"\n✅ Success! Processed image saved to: {output_path}")
        if args.debug:
            mask_path = Path(output_path).parent / f"{Path(args.image).stem}_mask.png"
            print(f"✅ Debug mask saved to: {mask_path}")
        
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
